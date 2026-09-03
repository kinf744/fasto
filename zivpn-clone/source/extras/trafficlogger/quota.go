package trafficlogger

import (
	"encoding/json"
	"os"
	"sync"
	"time"
)

// QuotaState is the persisted per-password byte counters and quota limits.
type QuotaState struct {
	Month  string            `json:"month"` // YYYY-MM of the current quota period
	Quotas map[string]uint64 `json:"quotas"`
	Used   map[string]uint64 `json:"used"`
}

// QuotaTrafficLogger implements server.TrafficLogger to track per-password
// data usage against a lifetime quota (usage commercial). Counters are
// persisted to a state file so they survive restarts. Le reset mensuel
// automatique a été DÉSACTIVÉ le 2026-09-03 : le quota est désormais
// cumulatif lifetime, pas mensuel — il ne se remet pas à 0 au 1er du mois.
// Le panel install2.py gère aussi le cumul côté Python pour compatibilité
// avec les anciens binaires.
//
// The Log method returns false once a password has consumed its quota, which
// causes the server to disconnect the client.
type QuotaTrafficLogger struct {
	Mutex     sync.Mutex
	Month     string
	Quotas    map[string]uint64
	Used      map[string]uint64
	StateFile string
	OnExceed  func(id string, used, quota uint64)
}

// NewQuotaTrafficLogger builds a QuotaTrafficLogger from a password→quota map
// (quota in bytes) and loads any previously persisted usage from stateFile.
func NewQuotaTrafficLogger(quotas map[string]uint64, stateFile string, onExceed func(id string, used, quota uint64)) *QuotaTrafficLogger {
	q := &QuotaTrafficLogger{
		Month:     time.Now().Format("2006-01"),
		Quotas:    quotas,
		Used:      make(map[string]uint64, len(quotas)),
		StateFile: stateFile,
		OnExceed:  onExceed,
	}
	q.load()
	return q
}

func (q *QuotaTrafficLogger) Log(id string, tx, rx uint64) (ok bool) {
	q.Mutex.Lock()
	defer q.Mutex.Unlock()

	q.rolloverLocked()

	quota, hasQuota := q.Quotas[id]
	if !hasQuota {
		// No quota configured for this password: allow freely.
		return true
	}

	used := q.Used[id] + tx + rx
	q.Used[id] = used
	if quota > 0 && used > quota {
		if q.OnExceed != nil {
			q.OnExceed(id, used, quota)
		}
		return false
	}
	return true
}

// Save persists the current counters to the state file.
func (q *QuotaTrafficLogger) Save() error {
	q.Mutex.Lock()
	defer q.Mutex.Unlock()
	q.rolloverLocked()
	return q.saveLocked()
}

// UsedNow returns the currently used bytes for a password.
func (q *QuotaTrafficLogger) UsedNow(id string) uint64 {
	q.Mutex.Lock()
	defer q.Mutex.Unlock()
	q.rolloverLocked()
	return q.Used[id]
}

// Usage returns the currently used bytes for a user id.
func (q *QuotaTrafficLogger) Usage(id string) uint64 {
	return q.UsedNow(id)
}

// Quota returns the configured monthly quota (bytes) for a user id.
func (q *QuotaTrafficLogger) Quota(id string) uint64 {
	q.Mutex.Lock()
	defer q.Mutex.Unlock()
	return q.Quotas[id]
}

// ResetUsage zeroes the used counter for a user id, or all users if id is empty.
func (q *QuotaTrafficLogger) ResetUsage(id string) {
	q.Mutex.Lock()
	defer q.Mutex.Unlock()
	if id == "" {
		for k := range q.Used {
			delete(q.Used, k)
		}
	} else {
		delete(q.Used, id)
	}
	_ = q.saveLocked()
}

// IDs returns the configured user ids (password list).
func (q *QuotaTrafficLogger) IDs() []string {
	q.Mutex.Lock()
	defer q.Mutex.Unlock()
	ids := make([]string, 0, len(q.Quotas))
	for id := range q.Quotas {
		ids = append(ids, id)
	}
	return ids
}

// rolloverLocked historiquement remettait à 0 au changement de mois.
// Désactivé : quota lifetime. On conserve la méthode no-op pour compatibilité
// binaire (évite de casser les appels existants) mais on ne supprime plus rien.
// Callers must hold q.Mutex.
func (q *QuotaTrafficLogger) rolloverLocked() {
	// No-op : quota lifetime, pas de reset mensuel
	// On met à jour Month pour la persistance mais on garde Used intact
	now := time.Now().Format("2006-01")
	if now != q.Month {
		q.Month = now
		_ = q.saveLocked()
	}
}

func (q *QuotaTrafficLogger) saveLocked() error {
	if q.StateFile == "" {
		return nil
	}
	st := QuotaState{
		Month:  q.Month,
		Quotas: q.Quotas,
		Used:   q.Used,
	}
	data, err := json.Marshal(st)
	if err != nil {
		return err
	}
	return os.WriteFile(q.StateFile, data, 0o644)
}

func (q *QuotaTrafficLogger) load() {
	if q.StateFile == "" {
		return
	}
	data, err := os.ReadFile(q.StateFile)
	if err != nil {
		return
	}
	var st QuotaState
	if err := json.Unmarshal(data, &st); err != nil {
		return
	}
	// Quota lifetime : on charge Used même si le mois a changé
	if st.Used != nil {
		q.Used = st.Used
	}
	// Si le fichier vient d'un ancien binaire mensuel, on garde le mois
	// courant en mémoire mais on ne jette plus Used
	if st.Month != "" {
		q.Month = st.Month
		// On force la sauvegarde avec le mois courant pour migrer le fichier
		now := time.Now().Format("2006-01")
		if q.Month != now {
			q.Month = now
		}
	}
}