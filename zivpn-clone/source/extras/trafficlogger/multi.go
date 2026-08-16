package trafficlogger

import "github.com/apernet/hysteria/core/server"

// MultiTrafficLogger combines several TrafficLogger implementations into one,
// forwarding every Log call to each of them. A Log call returns false if any
// of the underlying loggers requests a disconnect.
type MultiTrafficLogger struct {
	loggers []server.TrafficLogger
}

func NewMultiTrafficLogger(loggers ...server.TrafficLogger) *MultiTrafficLogger {
	return &MultiTrafficLogger{loggers: loggers}
}

func (m *MultiTrafficLogger) Log(id string, tx, rx uint64) (ok bool) {
	for _, l := range m.loggers {
		if l != nil && !l.Log(id, tx, rx) {
			return false
		}
	}
	return true
}