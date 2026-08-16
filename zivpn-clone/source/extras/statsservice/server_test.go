package statsservice

import (
	"context"
	"net"
	"testing"
	"time"
)

// fakeProvider implements QuotaProvider for tests.
type fakeProvider struct {
	usage  map[string]uint64
	quota  map[string]uint64
	resets []string
}

func (f *fakeProvider) Usage(id string) uint64 { return f.usage[id] }
func (f *fakeProvider) Quota(id string) uint64 { return f.quota[id] }
func (f *fakeProvider) ResetUsage(id string)   { f.resets = append(f.resets, id) }
func (f *fakeProvider) IDs() []string          { return []string{"Alice", "Bob"} }

func freePort(t *testing.T) string {
	lis, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	addr := lis.Addr().String()
	lis.Close()
	return addr
}

func TestServerGetStats(t *testing.T) {
	fp := &fakeProvider{usage: map[string]uint64{"Alice": 1234}, quota: map[string]uint64{"Alice": 5000}}
	s := NewServer(fp)
	addr := freePort(t)

	grpcServer, err := s.Serve(addr)
	if err != nil {
		t.Fatal(err)
	}
	defer grpcServer.Stop()

	client, conn, err := DialStatsService(context.Background(), addr)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	resp, err := client.GetStats(ctx, &GetStatsRequest{Name: "Alice"})
	if err != nil {
		t.Fatal(err)
	}
	if resp.GetStat().GetName() != "user>>>Alice" {
		t.Fatalf("name = %q", resp.GetStat().GetName())
	}
	if resp.GetStat().GetValue() != 1234 {
		t.Fatalf("value = %d, want 1234", resp.GetStat().GetValue())
	}
	if resp.GetStat().GetQuota() != 5000 {
		t.Fatalf("quota = %d, want 5000", resp.GetStat().GetQuota())
	}
}

func TestServerQueryAndReset(t *testing.T) {
	fp := &fakeProvider{usage: map[string]uint64{"Alice": 1, "Bob": 2}, quota: map[string]uint64{"Bob": 9}}
	s := NewServer(fp)
	addr := freePort(t)

	grpcServer, err := s.Serve(addr)
	if err != nil {
		t.Fatal(err)
	}
	defer grpcServer.Stop()

	client, conn, err := DialStatsService(context.Background(), addr)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	resp, err := client.QueryStats(ctx, &QueryStatsRequest{})
	if err != nil {
		t.Fatal(err)
	}
	if len(resp.GetStats()) != 2 {
		t.Fatalf("stats len = %d, want 2", len(resp.GetStats()))
	}

	if _, err := client.ResetStats(ctx, &ResetStatsRequest{Name: "Alice"}); err != nil {
		t.Fatal(err)
	}
	found := false
	for _, r := range fp.resets {
		if r == "Alice" {
			found = true
		}
	}
	if !found {
		t.Fatal("ResetUsage not called for Alice")
	}
}