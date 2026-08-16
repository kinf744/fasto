package trafficlogger

import (
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"
)

func TestQuotaTrafficLoggerBasic(t *testing.T) {
	quotas := map[string]uint64{"u1": 100, "u2": 1000}
	ql := NewQuotaTrafficLogger(quotas, "", nil)

	if ok := ql.Log("u1", 60, 0); !ok {
		t.Fatal("u1 should pass under quota")
	}
	if ok := ql.Log("u1", 60, 0); ok {
		t.Fatal("u1 should be disconnected at 120 > 100")
	}
	if ok := ql.Log("u2", 999, 0); !ok {
		t.Fatal("u2 should pass")
	}
	// Unknown password: no quota -> allowed.
	if ok := ql.Log("ghost", 999999, 999999); !ok {
		t.Fatal("unknown password should be allowed")
	}
}

func TestQuotaTrafficLoggerPersist(t *testing.T) {
	dir := t.TempDir()
	stateFile := filepath.Join(dir, "state.json")
	quotas := map[string]uint64{"u1": 1000}

	ql := NewQuotaTrafficLogger(quotas, stateFile, nil)
	if ok := ql.Log("u1", 300, 0); !ok {
		t.Fatal("should pass")
	}
	if err := ql.Save(); err != nil {
		t.Fatal(err)
	}
	if !fileExists(stateFile) {
		t.Fatal("state file not written")
	}

	// Reload from disk: usage must be restored.
	ql2 := NewQuotaTrafficLogger(quotas, stateFile, nil)
	if got := ql2.UsedNow("u1"); got != 300 {
		t.Fatalf("restored usage = %d, want 300", got)
	}
	// Reaching the quota exactly is still allowed; exceeding it is not.
	if ok := ql2.Log("u1", 700, 0); !ok {
		t.Fatal("should still pass at exactly 1000")
	}
	if ok := ql2.Log("u1", 1, 0); ok {
		t.Fatal("should be disconnected at 1001 > 1000")
	}
}

func TestQuotaTrafficLoggerOnExceed(t *testing.T) {
	var exceeded int32
	quotas := map[string]uint64{"u1": 50}
	ql := NewQuotaTrafficLogger(quotas, "", func(id string, used, quota uint64) {
		atomic.AddInt32(&exceeded, 1)
	})
	ql.Log("u1", 100, 0)
	if atomic.LoadInt32(&exceeded) != 1 {
		t.Fatal("OnExceed not called")
	}
}

func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}