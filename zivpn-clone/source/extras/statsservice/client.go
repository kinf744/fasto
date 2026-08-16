package statsservice

import (
	"context"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

// DialStatsService connects to a running StatsService gRPC server.
func DialStatsService(ctx context.Context, addr string) (StatsServiceClient, *grpc.ClientConn, error) {
	conn, err := grpc.NewClient(addr,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
	)
	if err != nil {
		return nil, nil, err
	}
	return NewStatsServiceClient(conn), conn, nil
}