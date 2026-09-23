package trafficlogger

import (
	"os"
	"path/filepath"
	"strings"
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
func TestQuotaStateChecksumAndBackup(t *testing.T) {
	dir := t.TempDir()
	stateFile := filepath.Join(dir, "state.json")
	quotas := map[string]uint64{"u1": 10000}

	ql := NewQuotaTrafficLogger(quotas, stateFile, nil)
	ql.Log("u1", 1234, 0)
	if err := ql.Save(); err != nil {
		t.Fatal(err)
	}
	// Main + backup both written, with version tag.
	if !fileExists(stateFile) || !fileExists(stateFile+".bak") {
		t.Fatal("main or backup state file missing")
	}
	data, _ := os.ReadFile(stateFile)
	if !containsStr(string(data), `"version":2`) {
		t.Fatal("state file not versioned")
	}

	// Corrupt the MAIN file: counters must be restored from .bak.
	if err := os.WriteFile(stateFile, []byte("{garbage"), 0o644); err != nil {
		t.Fatal(err)
	}
	ql2 := NewQuotaTrafficLogger(quotas, stateFile, nil)
	if got := ql2.UsedNow("u1"); got != 1234 {
		t.Fatalf("backup restore failed: got %d, want 1234", got)
	}
}

func TestQuotaStateTamperedChecksum(t *testing.T) {
	dir := t.TempDir()
	stateFile := filepath.Join(dir, "state.json")
	quotas := map[string]uint64{"u1": 10000}

	ql := NewQuotaTrafficLogger(quotas, stateFile, nil)
	ql.Log("u1", 500, 0)
	if err := ql.Save(); err != nil {
		t.Fatal(err)
	}
	// Tamper the counter in the main file without fixing the checksum:
	// load must refuse the tampered data.
	data, _ := os.ReadFile(stateFile)
	tampered := []byte(strings.Replace(string(data), `"u1":500`, `"u1":99999`, 1))
	os.WriteFile(stateFile, tampered, 0o644)
	if _, ok := loadStateFile(stateFile); ok {
		t.Fatal("tampered checksum accepted")
	}
}

func containsStr(s, sub string) bool {
	return strings.Contains(s, sub)
}
