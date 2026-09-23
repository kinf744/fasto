package trafficlogger

import (
	"encoding/json"
	"hash/crc32"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// QuotaStateVersion identifies the persisted state schema. Bump it whenever
// the structure changes so future migrations can be explicit and safe.
const QuotaStateVersion = 2

// QuotaState is the persisted per-password byte counters and quota limits.
// Checksum is a CRC32 (IEEE) over the canonical JSON encoding of the state
// with Checksum forced to 0 : it lets us detect a torn/corrupted write and
// fall back to the backup copy instead of silently resetting counters.
type QuotaState struct {
	Version  int               `json:"version"`
	Checksum uint32            `json:"checksum"`
	Month    string            `json:"month"` // YYYY-MM of the current quota period
	Quotas   map[string]uint64 `json:"quotas"`
	Used     map[string]uint64 `json:"used"`
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

// marshalState encodes the state canonically. With zeroChecksum=false the
// stored Checksum is computed over the encoding with Checksum == 0.
func marshalState(st *QuotaState, zeroChecksum bool) ([]byte, error) {
	cpy := *st
	cpy.Version = QuotaStateVersion
	cpy.Checksum = 0
	data, err := json.Marshal(&cpy)
	if err != nil {
		return nil, err
	}
	if zeroChecksum {
		return data, nil
	}
	cpy.Checksum = crc32.ChecksumIEEE(data)
	return json.Marshal(&cpy)
}

// stateChecksumOK verifies the embedded CRC32. Legacy files (version <= 1,
// no checksum written by older binaries) are accepted as-is so an upgrade
// never loses counters; they are rewritten to v2 on the next Save.
func stateChecksumOK(st *QuotaState) bool {
	if st.Version < 2 {
		return true
	}
	data, err := marshalState(st, true)
	if err != nil {
		return false
	}
	return crc32.ChecksumIEEE(data) == st.Checksum
}

// writeFileAtomic writes data via a temp file + rename in the same
// directory, so a crash never leaves a truncated state file.
func writeFileAtomic(path string, data []byte, perm os.FileMode) error {
	dir := filepath.Dir(path)
	tmp, err := os.CreateTemp(dir, ".quota-state-*.tmp")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	defer os.Remove(tmpName)
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmpName, path)
}

// saveLocked writes the state atomically to the main file AND to a ".bak"
// mirror. The backup costs nothing and survives a corruption of the main
// file (disk error, partial fsync, accidental manual edit).
// Callers must hold q.Mutex.
func (q *QuotaTrafficLogger) saveLocked() error {
	if q.StateFile == "" {
		return nil
	}
	st := QuotaState{
		Month:  q.Month,
		Quotas: q.Quotas,
		Used:   q.Used,
	}
	data, err := marshalState(&st, false)
	if err != nil {
		return err
	}
	err = writeFileAtomic(q.StateFile, data, 0o644)
	if bakErr := writeFileAtomic(q.StateFile+".bak", data, 0o644); bakErr != nil && err == nil {
		err = bakErr
	}
	return err
}

// load reads the state file, verifies its integrity and falls back to the
// ".bak" mirror if the main file is missing, unparsable or has a bad
// checksum. A corrupted state must NEVER silently zero the counters.
func (q *QuotaTrafficLogger) load() {
	if q.StateFile == "" {
		return
	}
	st, ok := loadStateFile(q.StateFile)
	if !ok {
		st, ok = loadStateFile(q.StateFile + ".bak")
	}
	if !ok {
		return
	}
	// Quota lifetime : on charge Used même si le mois a changé
	if st.Used != nil {
		q.Used = st.Used
	}
	// On conserve aussi les quotas persistés pour le diagnostic ; la config
	// reste prioritaire (NewQuotaTrafficLogger a déjà peuplé q.Quotas).
	if st.Month != "" {
		q.Month = st.Month
		now := time.Now().Format("2006-01")
		if q.Month != now {
			q.Month = now
		}
	}
}

func loadStateFile(path string) (*QuotaState, bool) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, false
	}
	var st QuotaState
	if err := json.Unmarshal(data, &st); err != nil {
		return nil, false
	}
	if !stateChecksumOK(&st) {
		return nil, false
	}
	return &st, true
}
