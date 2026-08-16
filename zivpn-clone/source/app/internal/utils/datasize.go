package utils

import (
	"fmt"
	"strconv"
	"strings"
)

var dataSizeUnits = []struct {
	suffix string
	value  uint64
}{
	{"KIB", 1024},
	{"MIB", 1024 * 1024},
	{"GIB", 1024 * 1024 * 1024},
	{"TIB", 1024 * 1024 * 1024 * 1024},
	{"PIB", 1024 * 1024 * 1024 * 1024 * 1024},
	{"KB", 1000},
	{"MB", 1000 * 1000},
	{"GB", 1000 * 1000 * 1000},
	{"TB", 1000 * 1000 * 1000 * 1000},
	{"PB", 1000 * 1000 * 1000 * 1000 * 1000},
	{"B", 1},
}

// ParseDataSize parses a human-readable data size string (e.g. "10GB", "500MB",
// "1TiB", "1048576") into a byte count. A plain number without a unit is
// treated as bytes.
func ParseDataSize(s string) (uint64, error) {
	s = strings.TrimSpace(s)
	if s == "" {
		return 0, fmt.Errorf("empty data size")
	}
	upper := strings.ToUpper(s)
	for _, u := range dataSizeUnits {
		if strings.HasSuffix(upper, u.suffix) {
			num := strings.TrimSpace(strings.TrimSuffix(upper, u.suffix))
			v, err := strconv.ParseUint(num, 10, 64)
			if err != nil {
				return 0, fmt.Errorf("invalid data size %q: %v", s, err)
			}
			return v * u.value, nil
		}
	}
	v, err := strconv.ParseUint(upper, 10, 64)
	if err != nil {
		return 0, fmt.Errorf("invalid data size %q: %v", s, err)
	}
	return v, nil
}