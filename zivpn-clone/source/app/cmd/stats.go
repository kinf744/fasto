package cmd

import (
	"context"
	"fmt"
	"os"
	"strings"

	"github.com/apernet/hysteria/extras/statsservice"
	"github.com/spf13/cobra"
)

var statsCmd = &cobra.Command{
	Use:   "stats",
	Short: "Query per-password traffic usage from the server stats API",
	Run: func(cmd *cobra.Command, args []string) {
		addr := statsServerAddr
		ctx := context.Background()
		client, conn, err := statsservice.DialStatsService(ctx, addr)
		if err != nil {
			fmt.Fprintf(os.Stderr, "failed to connect to stats API at %s: %v\n", addr, err)
			os.Exit(1)
		}
		defer conn.Close()

		resp, err := client.QueryStats(ctx, &statsservice.QueryStatsRequest{})
		if err != nil {
			fmt.Fprintf(os.Stderr, "failed to query stats: %v\n", err)
			os.Exit(1)
		}

		if len(resp.GetStats()) == 0 {
			fmt.Println("no users with quota configured")
			return
		}
		fmt.Printf("%-16s %14s %14s %10s\n", "PASSWORD", "USED", "QUOTA", "USED%")
		for _, st := range resp.GetStats() {
			id := strings.TrimPrefix(st.GetName(), "user>>>")
			used := st.GetValue()
			quota := st.GetQuota()
			var pct string
			if quota > 0 {
				pct = fmt.Sprintf("%.2f%%", float64(used)/float64(quota)*100)
			} else {
				pct = "-"
			}
			fmt.Printf("%-16s %14s %14s %10s\n", id, humanBytes(used), humanBytes(quota), pct)
		}
	},
}

func humanBytes(b int64) string {
	if b < 0 {
		return "0 B"
	}
	const unit = 1000
	if b < unit {
		return fmt.Sprintf("%d B", b)
	}
	div, exp := int64(unit), 0
	for n := b / unit; n >= unit; n /= unit {
		div *= unit
		exp++
	}
	return fmt.Sprintf("%.2f %cB", float64(b)/float64(div), "kMGTPE"[exp])
}

var statsServerAddr string

func init() {
	statsCmd.Flags().StringVar(&statsServerAddr, "addr", "127.0.0.1:10085", "stats API server address")
	rootCmd.AddCommand(statsCmd)
}