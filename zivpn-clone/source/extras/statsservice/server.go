package statsservice

import (
	"context"
	"fmt"
	"net"
	"os"
	"time"

	"google.golang.org/grpc"
)

// QuotaProvider abstracts access to the quota logger so the gRPC service can
// query usage per user without depending on the concrete type.
type QuotaProvider interface {
	// Usage returns the current used bytes for a user id.
	Usage(id string) uint64
	// Quota returns the configured monthly quota (bytes) for a user id.
	Quota(id string) uint64
	// ResetUsage zeroes the used counter for a user id (or all if id == "").
	ResetUsage(id string)
	// IDs returns the configured user ids.
	IDs() []string
}

// Server is a gRPC server exposing the StatsService API over a local socket.
type Server struct {
	UnimplementedStatsServiceServer
	provider QuotaProvider
}

func NewServer(provider QuotaProvider) *Server {
	return &Server{provider: provider}
}

func (s *Server) GetStats(ctx context.Context, req *GetStatsRequest) (*GetStatsResponse, error) {
	id := req.GetName()
	if id == "" {
		return nil, fmt.Errorf("empty name")
	}
	stat := s.statFor(id)
	if req.GetReset_() {
		s.provider.ResetUsage(id)
	}
	return &GetStatsResponse{Stat: stat}, nil
}

func (s *Server) QueryStats(ctx context.Context, req *QueryStatsRequest) (*QueryStatsResponse, error) {
	ids := s.provider.IDs()
	stats := make([]*Stat, 0, len(ids))
	for _, id := range ids {
		stats = append(stats, s.statFor(id))
	}
	if req.GetReset_() {
		s.provider.ResetUsage("")
	}
	return &QueryStatsResponse{Stats: stats}, nil
}

func (s *Server) ResetStats(ctx context.Context, req *ResetStatsRequest) (*ResetStatsResponse, error) {
	s.provider.ResetUsage(req.GetName())
	return &ResetStatsResponse{Ok: true}, nil
}

func (s *Server) statFor(id string) *Stat {
	used := s.provider.Usage(id)
	quota := s.provider.Quota(id)
	return &Stat{
		Name:    "user>>>" + id,
		Value:   int64(used),
		Quota:   int64(quota),
		Updated: time.Now().Unix(),
	}
}

// Serve listens on addr and serves the StatsService. The returned gRPC server
// can be stopped with Stop()/GracefulStop().
func (s *Server) Serve(addr string) (*grpc.Server, error) {
	lis, err := net.Listen("tcp", addr)
	if err != nil {
		return nil, err
	}
	grpcServer := grpc.NewServer()
	RegisterStatsServiceServer(grpcServer, s)
	go func() {
		if err := grpcServer.Serve(lis); err != nil {
			// Only surface fatal errors; ErrServerStopped is expected on stop.
			if err != grpc.ErrServerStopped {
				fmt.Fprintf(os.Stderr, "stats API server error: %v\n", err)
			}
		}
	}()
	return grpcServer, nil
}