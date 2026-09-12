// sshws v2 — TCP RAW Injector + WebSocket → SSH (durci)
// Compatible flags v1 : -listen -target-host -target-port
// Nouveautés : handshake strict, timeouts, mode raw|ws|auto, paths,
// TLS optionnel (WSS autonome), PROXY v1 auto, limites, métriques.
//
// Architecture recommandée :
//
//	WS  80  : clients -> sshws:80 (clair)
//	WSS 443 : clients -> HAProxy:443 (TLS) -> backend ssh-wss -> sshws:127.0.0.1:80
//
// Le binaire reste en clair par défaut ; -tls-cert/-tls-key pour WSS direct.
//
// Go 1.22+, stdlib uniquement.
package main

import (
	"bufio"
	"crypto/sha1"
	"crypto/tls"
	"encoding/base64"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

const (
	wsGUID  = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
	version = "sshws v2.0.0"
)

var (
	fListen      = flag.String("listen", "80", "Listen port (ou addr:port)")
	fTargetHost  = flag.String("target-host", "127.0.0.1", "SSH host")
	fTargetPort  = flag.String("target-port", "1092", "SSH port")
	fMode        = flag.String("mode", "auto", "Relay après handshake WS: raw|ws|auto")
	fPaths       = flag.String("paths", "/ssh-wss,/ssh-ws,/ws", "Paths WS autorisés (csv, vide=tous)")
	fTLSCert     = flag.String("tls-cert", "", "Cert PEM pour WSS direct (vide=clair)")
	fTLSKey      = flag.String("tls-key", "", "Clé PEM pour WSS direct")
	fMaxConns    = flag.Int("max-conns", 2048, "Connexions simultanées max")
	fHsTimeout   = flag.Duration("handshake-timeout", 5*time.Second, "Deadline handshake")
	fIdleTimeout = flag.Duration("idle-timeout", 5*time.Minute, "Idle timeout relay")
	fDialTimeout = flag.Duration("dial-timeout", 5*time.Second, "Dial target")
	fAllowRaw    = flag.Bool("allow-raw", true, "Autorise injecteur TCP RAW sans Upgrade (compat v1)")
	fAllowProxy  = flag.Bool("allow-proxy", true, "Parse PROXY v1 HAProxy auto")
	fMetrics     = flag.String("metrics-listen", "", "Ex: 127.0.0.1:14080 (/metrics,/healthz, vide=off)")
	fLogFile     = flag.String("log-file", "", "Fichier log (vide=stderr/journal)")
	fLogLevel    = flag.String("log-level", "info", "quiet|info|debug")
	fShowVersion = flag.Bool("version", false, "Affiche version")
)

var (
	activeConns int64
	totalConns  int64
	bytesCT     int64 // client -> target
	bytesTC     int64 // target -> client
	wsConns     int64
	rawConns    int64
	rejected    int64
)

func acceptKey(key string) string {
	h := sha1.New()
	h.Write([]byte(strings.TrimSpace(key) + wsGUID))
	return base64.StdEncoding.EncodeToString(h.Sum(nil))
}

func tuneConn(c net.Conn) {
	if tc, ok := c.(*net.TCPConn); ok {
		_ = tc.SetNoDelay(true)
		_ = tc.SetKeepAlive(true)
		_ = tc.SetKeepAlivePeriod(30 * time.Second)
	}
	// Buffers OS par défaut (pas de 4Mo/connexion comme v1 -> OOM).
}

func allowedPaths() map[string]bool {
	m := map[string]bool{}
	for _, p := range strings.Split(*fPaths, ",") {
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}
		if !strings.HasPrefix(p, "/") {
			p = "/" + p
		}
		m[p] = true
	}
	return m
}

func pathOf(target string) string {
	if i := strings.Index(target, "?"); i >= 0 {
		target = target[:i]
	}
	if i := strings.Index(target, "#"); i >= 0 {
		target = target[:i]
	}
	if target == "" {
		return "/"
	}
	return target
}

// copyIdle recopie avec idle deadline rafraîchie ; retourne octets.
func copyIdle(dst, src net.Conn, idle time.Duration, counter *int64) int64 {
	var total int64
	buf := make([]byte, 32*1024)
	for {
		if idle > 0 {
			_ = src.SetReadDeadline(time.Now().Add(idle))
		}
		n, err := src.Read(buf)
		if n > 0 {
			if idle > 0 {
				_ = dst.SetWriteDeadline(time.Now().Add(idle))
			}
			if _, werr := dst.Write(buf[:n]); werr != nil {
				break
			}
			total += int64(n)
			if counter != nil {
				atomic.AddInt64(counter, int64(n))
			}
		}
		if err != nil {
			break
		}
	}
	return total
}

// closeWrite tente un half-close, sinon close.
func closeWrite(c net.Conn) {
	if tc, ok := c.(*net.TCPConn); ok {
		_ = tc.CloseWrite()
		return
	}
	if tlsConn, ok := c.(*tls.Conn); ok {
		_ = tlsConn.CloseWrite()
		return
	}
	_ = c.Close()
}

func rawRelay(client, target net.Conn, idle time.Duration) {
	var wg sync.WaitGroup
	wg.Add(2)
	go func() { defer wg.Done(); copyIdle(target, client, idle, &bytesCT); closeWrite(target) }()
	go func() { defer wg.Done(); copyIdle(client, target, idle, &bytesTC); closeWrite(client) }()
	wg.Wait()
	_ = client.Close()
	_ = target.Close()
}

// ---- WS RFC6455 minimal (client masqué -> target brut ; target -> client binaire) ----

const maxFramePayload = 1 << 20 // 1Mo par message

type wsReader struct {
	r *bufio.Reader
}

func (w *wsReader) readFrame() (opcode byte, payload []byte, err error) {
	var hdr [2]byte
	if _, err = io.ReadFull(w.r, hdr[:]); err != nil {
		return
	}
	fin := hdr[0]&0x80 != 0
	op := hdr[0] & 0x0F
	masked := hdr[1]&0x80 != 0
	n := int64(hdr[1] & 0x7F)
	switch n {
	case 126:
		var ext [2]byte
		if _, err = io.ReadFull(w.r, ext[:]); err != nil {
			return
		}
		n = int64(ext[0])<<8 | int64(ext[1])
	case 127:
		var ext [8]byte
		if _, err = io.ReadFull(w.r, ext[:]); err != nil {
			return
		}
		n = 0
		for i := 0; i < 8; i++ {
			n = n<<8 | int64(ext[i])
		}
		if n < 0 {
			err = fmt.Errorf("ws: longueur négative")
			return
		}
	}
	if n > maxFramePayload {
		err = fmt.Errorf("ws: frame trop grosse (%d)", n)
		return
	}
	var mask [4]byte
	if masked {
		if _, err = io.ReadFull(w.r, mask[:]); err != nil {
			return
		}
	}
	payload = make([]byte, n)
	if _, err = io.ReadFull(w.r, payload); err != nil {
		return
	}
	if masked {
		for i := range payload {
			payload[i] ^= mask[i%4]
		}
	}
	opcode = op
	if !fin {
		err = fmt.Errorf("ws: fragmentation non supportée")
		return
	}
	return opcode, payload, nil
}

func wsWriteFrame(w net.Conn, opcode byte, p []byte) error {
	var hdr []byte
	hdr = append(hdr, 0x80|opcode)
	n := len(p)
	switch {
	case n < 126:
		hdr = append(hdr, byte(n))
	case n < 65536:
		hdr = append(hdr, 126, byte(n>>8), byte(n))
	default:
		hdr = append(hdr, 127, 0, 0, 0, 0, byte(n>>24), byte(n>>16), byte(n>>8), byte(n))
	}
	if _, err := w.Write(hdr); err != nil {
		return err
	}
	if len(p) > 0 {
		_, err := w.Write(p)
		return err
	}
	return nil
}

func wsRelay(client, target net.Conn, br *bufio.Reader, idle time.Duration) {
	// target -> client : frames binaires
	done := make(chan struct{})
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		defer func() {
			select {
			case <-done:
			default:
				close(done)
			}
		}()
		buf := make([]byte, 32*1024)
		for {
			if idle > 0 {
				_ = target.SetReadDeadline(time.Now().Add(idle))
			}
			n, err := target.Read(buf)
			if n > 0 {
				if idle > 0 {
					_ = client.SetWriteDeadline(time.Now().Add(idle))
				}
				if werr := wsWriteFrame(client, 0x2, buf[:n]); werr != nil {
					return
				}
				atomic.AddInt64(&bytesTC, int64(n))
			}
			if err != nil {
				_ = wsWriteFrame(client, 0x8, []byte{})
				return
			}
		}
	}()
	// client -> target : decode frames
	wr := &wsReader{r: br}
	for {
		if idle > 0 {
			_ = client.SetReadDeadline(time.Now().Add(idle))
		}
		op, payload, err := wr.readFrame()
		if err != nil {
			break
		}
		switch op {
		case 0x8: // close
			_ = wsWriteFrame(client, 0x8, []byte{})
			close(done)
			wg.Wait()
			_ = client.Close()
			_ = target.Close()
			return
		case 0x9: // ping
			if idle > 0 {
				_ = client.SetWriteDeadline(time.Now().Add(idle))
			}
			_ = wsWriteFrame(client, 0xA, payload)
			continue
		case 0xA: // pong
			continue
		case 0x1, 0x2: // text/binaire
			if len(payload) > 0 {
				if idle > 0 {
					_ = target.SetWriteDeadline(time.Now().Add(idle))
				}
				if _, err := target.Write(payload); err != nil {
					break
				}
				atomic.AddInt64(&bytesCT, int64(len(payload)))
			}
		default:
			break
		}
		select {
		case <-done:
			wg.Wait()
			_ = client.Close()
			_ = target.Close()
			return
		default:
		}
	}
	close(done)
	wg.Wait()
	_ = client.Close()
	_ = target.Close()
}

// looksLikeWSFrame : heuristique sur 2 premiers octets (auto-détection).
func looksLikeWSFrame(b []byte) bool {
	if len(b) < 2 {
		return false
	}
	fin := b[0]&0x80 != 0
	op := b[0] & 0x0F
	masked := b[1]&0x80 != 0
	if !fin {
		return false
	}
	if op != 0x1 && op != 0x2 && op != 0x8 && op != 0x9 && op != 0xA {
		return false
	}
	// D'un vrai client navigateur, les frames sont masquées.
	return masked
}

// readProxyV1 consomme une éventuelle ligne "PROXY TCP4 ..." et retourne l'IP source.
func readProxyV1(br *bufio.Reader) string {
	peek, err := br.Peek(6)
	if err != nil || string(peek) != "PROXY " {
		return ""
	}
	line, err := br.ReadString('\n')
	if err != nil || len(line) > 108 {
		return ""
	}
	parts := strings.Fields(strings.TrimSpace(line))
	if len(parts) >= 3 {
		return parts[2]
	}
	return ""
}

func handleConn(client net.Conn, target string, paths map[string]bool, sem chan struct{}) {
	defer func() { <-sem }()
	atomic.AddInt64(&totalConns, 1)
	n := atomic.AddInt64(&activeConns, 1)
	defer atomic.AddInt64(&activeConns, -1)
	_ = n

	remote := client.RemoteAddr().String()
	tuneConn(client)
	_ = client.SetDeadline(time.Now().Add(*fHsTimeout))
	br := bufio.NewReaderSize(client, 16*1024)

	realIP := remote
	if *fAllowProxy {
		if ip := readProxyV1(br); ip != "" {
			realIP = ip + " (proxy)"
		}
	}

	// Lit headers jusqu'à \r\n\r\n (max 16K).
	var head strings.Builder
	for head.Len() < 16*1024 {
		line, err := br.ReadString('\n')
		if err != nil {
			_ = client.Close()
			return
		}
		head.WriteString(line)
		if strings.Contains(head.String(), "\r\n\r\n") {
			break
		}
	}
	raw := head.String()
	if !strings.Contains(raw, "\r\n\r\n") {
		if *fLogLevel != "quiet" {
			log.Printf("[REJECT] %s headers trop gros", realIP)
		}
		atomic.AddInt64(&rejected, 1)
		_ = client.Close()
		return
	}
	lines := strings.Split(raw, "\r\n")
	reqLine := strings.SplitN(lines[0], " ", 3)
	if len(reqLine) != 3 {
		_ = client.Close()
		return
	}
	method := strings.ToUpper(reqLine[0])
	reqTarget := pathOf(reqLine[1])
	hdrs := map[string]string{}
	for _, ln := range lines[1:] {
		if ln == "" {
			break
		}
		if i := strings.Index(ln, ":"); i > 0 {
			hdrs[strings.ToLower(strings.TrimSpace(ln[:i]))] = strings.TrimSpace(ln[i+1:])
		}
	}
	up := hdrs["upgrade"]
	connH := strings.ToLower(hdrs["connection"])
	key := hdrs["sec-websocket-key"]
	ver := hdrs["sec-websocket-version"]
	isWS := strings.Contains(strings.ToLower(up), "websocket") && strings.Contains(connH, "upgrade")

	dialTarget := func() net.Conn {
		d, err := net.DialTimeout("tcp", target, *fDialTimeout)
		if err != nil {
			return nil
		}
		tuneConn(d)
		return d
	}

	// Cas TCP RAW legacy (pas d'Upgrade) : compat v1.
	if !isWS {
		if !*fAllowRaw {
			_, _ = client.Write([]byte("HTTP/1.1 426 Upgrade Required\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"))
			_ = client.Close()
			return
		}
		r := dialTarget()
		if r == nil {
			_, _ = client.Write([]byte("HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"))
			_ = client.Close()
			return
		}
		atomic.AddInt64(&rawConns, 1)
		_ = client.SetDeadline(time.Time{})
		if *fLogLevel != "quiet" {
			log.Printf("[TCP-RAW] %s %s %s", realIP, method, reqTarget)
		}
		_, _ = client.Write([]byte("HTTP/1.1 200 OK\r\nConnection: keep-alive\r\nContent-Length: 0\r\n\r\n"))
		rawRelay(client, r, *fIdleTimeout)
		return
	}

	// Upgrade WS : validations strictes.
	if method != "GET" {
		_, _ = client.Write([]byte("HTTP/1.1 405 Method Not Allowed\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"))
		_ = client.Close()
		atomic.AddInt64(&rejected, 1)
		return
	}
	if len(paths) > 0 {
		if _, ok := paths[reqTarget]; !ok {
			_, _ = client.Write([]byte("HTTP/1.1 404 Not Found\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"))
			_ = client.Close()
			atomic.AddInt64(&rejected, 1)
			if *fLogLevel == "debug" {
				log.Printf("[REJECT] %s path %s", realIP, reqTarget)
			}
			return
		}
	}
	if key == "" {
		_, _ = client.Write([]byte("HTTP/1.1 400 Bad Request\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"))
		_ = client.Close()
		atomic.AddInt64(&rejected, 1)
		return
	}
	if ver != "" && ver != "13" {
		_, _ = client.Write([]byte("HTTP/1.1 426 Upgrade Required\r\nSec-WebSocket-Version: 13\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"))
		_ = client.Close()
		atomic.AddInt64(&rejected, 1)
		return
	}

	resp := "HTTP/1.1 101 Switching Protocols\r\n" +
		"Upgrade: websocket\r\n" +
		"Connection: Upgrade\r\n" +
		"Sec-WebSocket-Accept: " + acceptKey(key) + "\r\n\r\n"
	_ = client.SetDeadline(time.Time{})
	if _, err := client.Write([]byte(resp)); err != nil {
		_ = client.Close()
		return
	}
	r := dialTarget()
	if r == nil {
		_ = client.Close()
		return
	}

	mode := strings.ToLower(*fMode)
	useWS := false
	if mode == "ws" {
		useWS = true
	} else if mode == "raw" {
		useWS = false
	} else {
		// auto : peek 300ms pour détecter une vraie frame WS masquée.
		_ = client.SetReadDeadline(time.Now().Add(300 * time.Millisecond))
		peek, err := br.Peek(2)
		_ = client.SetReadDeadline(time.Time{})
		if err == nil && looksLikeWSFrame(peek) {
			useWS = true
		} else {
			useWS = false
		}
	}
	if useWS {
		atomic.AddInt64(&wsConns, 1)
		if *fLogLevel != "quiet" {
			log.Printf("[WS] %s path=%s", realIP, reqTarget)
		}
		wsRelay(client, r, br, *fIdleTimeout)
	} else {
		atomic.AddInt64(&rawConns, 1)
		if *fLogLevel != "quiet" {
			log.Printf("[WS-RAW] %s path=%s", realIP, reqTarget)
		}
		// Rejoue les octets déjà bufferisés côté client->target.
		pending := br.Buffered()
		if pending > 0 {
			peeked, _ := br.Peek(pending)
			_ = r.SetWriteDeadline(time.Now().Add(*fIdleTimeout))
			if _, err := r.Write(peeked); err != nil {
				_ = client.Close()
				_ = r.Close()
				return
			}
			_, _ = br.Discard(pending)
			atomic.AddInt64(&bytesCT, int64(len(peeked)))
		}
		rawRelay(client, r, *fIdleTimeout)
	}
}

func serveMetrics(addr string) {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(200)
		_, _ = w.Write([]byte("ok"))
	})
	mux.HandleFunc("/metrics", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprintf(w, "sshws_active %d\nsshws_total %d\nsshws_ws %d\nsshws_raw %d\nsshws_rejected %d\nsshws_bytes_ct %d\nsshws_bytes_tc %d\n",
			atomic.LoadInt64(&activeConns), atomic.LoadInt64(&totalConns),
			atomic.LoadInt64(&wsConns), atomic.LoadInt64(&rawConns),
			atomic.LoadInt64(&rejected),
			atomic.LoadInt64(&bytesCT), atomic.LoadInt64(&bytesTC))
	})
	s := &http.Server{Addr: addr, Handler: mux, ReadTimeout: 5 * time.Second}
	_ = s.ListenAndServe()
}

func main() {
	runtime.GOMAXPROCS(runtime.NumCPU())
	flag.Parse()
	if *fShowVersion {
		fmt.Println(version)
		return
	}
	if *fLogFile != "" {
		f, err := os.OpenFile(*fLogFile, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
		if err != nil {
			log.Fatal(err)
		}
		defer f.Close()
		log.SetOutput(io.MultiWriter(os.Stdout, f))
	}
	log.SetFlags(log.LstdFlags)

	target := net.JoinHostPort(*fTargetHost, *fTargetPort)
	paths := allowedPaths()

	listenAddr := ":" + *fListen
	if strings.Contains(*fListen, ":") {
		listenAddr = *fListen
	}
	var ln net.Listener
	var err error
	if *fTLSCert != "" && *fTLSKey != "" {
		cert, err := tls.LoadX509KeyPair(*fTLSCert, *fTLSKey)
		if err != nil {
			log.Fatal(err)
		}
		ln, err = tls.Listen("tcp", listenAddr, &tls.Config{Certificates: []tls.Certificate{cert}, MinVersion: tls.VersionTLS12})
	} else {
		ln, err = net.Listen("tcp", listenAddr)
	}
	if err != nil {
		log.Fatal(err)
	}
	if *fMetrics != "" {
		go serveMetrics(*fMetrics)
	}
	tlsNote := ""
	if *fTLSCert != "" {
		tlsNote = " (TLS)"
	}
	log.Printf("%s actif sur %s%s -> %s [mode=%s paths=%s]", version, listenAddr, tlsNote, target, *fMode, *fPaths)

	sem := make(chan struct{}, *fMaxConns)
	for {
		c, err := ln.Accept()
		if err != nil {
			continue
		}
		select {
		case sem <- struct{}{}:
			go handleConn(c, target, paths, sem)
		default:
			atomic.AddInt64(&rejected, 1)
			_ = c.Close()
		}
	}
}
