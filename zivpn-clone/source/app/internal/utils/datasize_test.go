package utils

import "testing"

func TestParseDataSize(t *testing.T) {
	cases := []struct {
		in   string
		want uint64
		err  bool
	}{
		{"10GB", 10 * 1000 * 1000 * 1000, false},
		{"500MB", 500 * 1000 * 1000, false},
		{"1TB", 1000 * 1000 * 1000 * 1000, false},
		{"1TiB", 1024 * 1024 * 1024 * 1024, false},
		{"1048576", 1048576, false},
		{"0", 0, false},
		{"1KB", 1000, false},
		{"2KiB", 2048, false},
		{"bad", 0, true},
		{"", 0, true},
	}
	for _, c := range cases {
		got, err := ParseDataSize(c.in)
		if (err != nil) != c.err {
			t.Errorf("ParseDataSize(%q) err=%v, want err=%v", c.in, err, c.err)
		}
		if !c.err && got != c.want {
			t.Errorf("ParseDataSize(%q) = %d, want %d", c.in, got, c.want)
		}
	}
}
