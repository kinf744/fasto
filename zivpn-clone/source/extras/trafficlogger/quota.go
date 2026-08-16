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
// data usage against a monthly quota. Counters are persisted to a state file so
// they survive restarts, and reset automatically on the first day of each month.
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

// rolloverLocked resets all counters when the calendar month has changed.
// Callers must hold q.Mutex.
func (q *QuotaTrafficLogger) rolloverLocked() {
	now := time.Now().Format("2006-01")
	if now != q.Month {
		q.Month = now
		for k := range q.Used {
			delete(q.Used, k)
		}
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
	if st.Month == q.Month {
		q.Used = st.Used
	}
	// If the persisted month differs from the current one, counters are
	// discarded (monthly reset).
}