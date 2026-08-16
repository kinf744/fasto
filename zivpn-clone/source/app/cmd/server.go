package cmd

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/caddyserver/certmagic"
	"github.com/mholt/acmez/acme"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
	"github.com/yosuke-furukawa/json5/encoding/json5"
	"go.uber.org/zap"

	"github.com/apernet/hysteria/app/internal/utils"
	"github.com/apernet/hysteria/core/server"
	"github.com/apernet/hysteria/extras/auth"
	"github.com/apernet/hysteria/extras/correctnet"
	"github.com/apernet/hysteria/extras/masq"
	"github.com/apernet/hysteria/extras/obfs"
	"github.com/apernet/hysteria/extras/outbounds"
	"github.com/apernet/hysteria/extras/statsservice"
	"github.com/apernet/hysteria/extras/trafficlogger"
)

const (
	defaultListenAddr = ":443"
)

var serverCmd = &cobra.Command{
	Use:   "server",
	Short: "Server mode",
	Run:   runServer,
}

func init() {
	rootCmd.AddCommand(serverCmd)
}

type serverConfig struct {
	Listen                string                      `mapstructure:"listen"`
	Obfs                  serverConfigObfs            `mapstructure:"obfs"`
	Cert                  string                      `mapstructure:"cert"`
	Key                   string                      `mapstructure:"key"`
	TLS                   *serverConfigTLS            `mapstructure:"tls"`
	ACME                  *serverConfigACME           `mapstructure:"acme"`
	QUIC                  serverConfigQUIC            `mapstructure:"quic"`
	Bandwidth             serverConfigBandwidth       `mapstructure:"bandwidth"`
	IgnoreClientBandwidth bool                        `mapstructure:"ignoreClientBandwidth"`
	DisableUDP            bool                        `mapstructure:"disableUDP"`
	UDPIdleTimeout        time.Duration               `mapstructure:"udpIdleTimeout"`
	Auth                  serverConfigAuth            `mapstructure:"auth"`
	Quota                 map[string]string           `mapstructure:"quota"`
	QuotaStateFile        string                      `mapstructure:"quotaStateFile"`
	Resolver              serverConfigResolver        `mapstructure:"resolver"`
	ACL                   serverConfigACL             `mapstructure:"acl"`
	Outbounds             []serverConfigOutboundEntry `mapstructure:"outbounds"`
	TrafficStats          serverConfigTrafficStats    `mapstructure:"trafficStats"`
	StatsAPI              serverConfigStatsAPI        `mapstructure:"statsAPI"`
	Masquerade            serverConfigMasquerade      `mapstructure:"masquerade"`
}

type serverConfigStatsAPI struct {
	Listen string `mapstructure:"listen"`
}

type serverConfigObfsSalamander struct {
	Password string `json:"password"`
}

type serverConfigObfs struct {
	Type       string                     `json:"type"`
	Salamander serverConfigObfsSalamander `json:"salamander"`
}

func (o *serverConfigObfs) UnmarshalJSON(data []byte) error {
	var s string
	if err := json.Unmarshal(data, &s); err == nil {
		o.Type = s
		return nil
	}
	type obfsAlias serverConfigObfs
	var a obfsAlias
	if err := json.Unmarshal(data, &a); err != nil {
		return err
	}
	*o = serverConfigObfs(a)
	return nil
}

type serverConfigTLS struct {
	Cert string `mapstructure:"cert"`
	Key  string `mapstructure:"key"`
}

type serverConfigACME struct {
	Domains        []string `mapstructure:"domains"`
	Email          string   `mapstructure:"email"`
	CA             string   `mapstructure:"ca"`
	DisableHTTP    bool     `mapstructure:"disableHTTP"`
	DisableTLSALPN bool     `mapstructure:"disableTLSALPN"`
	AltHTTPPort    int      `mapstructure:"altHTTPPort"`
	AltTLSALPNPort int      `mapstructure:"altTLSALPNPort"`
	Dir            string   `mapstructure:"dir"`
}

type serverConfigQUIC struct {
	InitStreamReceiveWindow     uint64        `mapstructure:"initStreamReceiveWindow"`
	MaxStreamReceiveWindow      uint64        `mapstructure:"maxStreamReceiveWindow"`
	InitConnectionReceiveWindow uint64        `mapstructure:"initConnReceiveWindow"`
	MaxConnectionReceiveWindow  uint64        `mapstructure:"maxConnReceiveWindow"`
	MaxIdleTimeout              time.Duration `mapstructure:"maxIdleTimeout"`
	MaxIncomingStreams          int64         `mapstructure:"maxIncomingStreams"`
	DisablePathMTUDiscovery     bool          `mapstructure:"disablePathMTUDiscovery"`
}

type serverConfigBandwidth struct {
	Up   string `mapstructure:"up"`
	Down string `mapstructure:"down"`
}

type serverConfigAuthHTTP struct {
	URL      string `mapstructure:"url"`
	Insecure bool   `mapstructure:"insecure"`
}

type serverConfigAuth struct {
	Mode     string               `mapstructure:"mode"`
	Type     string               `mapstructure:"type"`
	Password string               `mapstructure:"password"`
	Config   []string             `mapstructure:"config"`
	UserPass map[string]string    `mapstructure:"userpass"`
	HTTP     serverConfigAuthHTTP `mapstructure:"http"`
	Command  string               `mapstructure:"command"`
}

type serverConfigResolverTCP struct {
	Addr    string        `mapstructure:"addr"`
	Timeout time.Duration `mapstructure:"timeout"`
}

type serverConfigResolverUDP struct {
	Addr    string        `mapstructure:"addr"`
	Timeout time.Duration `mapstructure:"timeout"`
}

type serverConfigResolverTLS struct {
	Addr     string        `mapstructure:"addr"`
	Timeout  time.Duration `mapstructure:"timeout"`
	SNI      string        `mapstructure:"sni"`
	Insecure bool          `mapstructure:"insecure"`
}

type serverConfigResolverHTTPS struct {
	Addr     string        `mapstructure:"addr"`
	Timeout  time.Duration `mapstructure:"timeout"`
	SNI      string        `mapstructure:"sni"`
	Insecure bool          `mapstructure:"insecure"`
}

type serverConfigResolver struct {
	Type  string                    `mapstructure:"type"`
	TCP   serverConfigResolverTCP   `mapstructure:"tcp"`
	UDP   serverConfigResolverUDP   `mapstructure:"udp"`
	TLS   serverConfigResolverTLS   `mapstructure:"tls"`
	HTTPS serverConfigResolverHTTPS `mapstructure:"https"`
}

type serverConfigACL struct {
	File              string        `mapstructure:"file"`
	Inline            []string      `mapstructure:"inline"`
	GeoIP             string        `mapstructure:"geoip"`
	GeoSite           string        `mapstructure:"geosite"`
	GeoUpdateInterval time.Duration `mapstructure:"geoUpdateInterval"`
}

type serverConfigOutboundDirect struct {
	Mode       string `mapstructure:"mode"`
	BindIPv4   string `mapstructure:"bindIPv4"`
	BindIPv6   string `mapstructure:"bindIPv6"`
	BindDevice string `mapstructure:"bindDevice"`
}

type serverConfigOutboundSOCKS5 struct {
	Addr     string `mapstructure:"addr"`
	Username string `mapstructure:"username"`
	Password string `mapstructure:"password"`
}

type serverConfigOutboundHTTP struct {
	URL      string `mapstructure:"url"`
	Insecure bool   `mapstructure:"insecure"`
}

type serverConfigOutboundEntry struct {
	Name   string                     `mapstructure:"name"`
	Type   string                     `mapstructure:"type"`
	Direct serverConfigOutboundDirect `mapstructure:"direct"`
	SOCKS5 serverConfigOutboundSOCKS5 `mapstructure:"socks5"`
	HTTP   serverConfigOutboundHTTP   `mapstructure:"http"`
}

type serverConfigTrafficStats struct {
	Listen string `mapstructure:"listen"`
	Secret string `mapstructure:"secret"`
}

type serverConfigMasqueradeFile struct {
	Dir string `mapstructure:"dir"`
}

type serverConfigMasqueradeProxy struct {
	URL         string `mapstructure:"url"`
	RewriteHost bool   `mapstructure:"rewriteHost"`
}

type serverConfigMasqueradeString struct {
	Content    string            `mapstructure:"content"`
	Headers    map[string]string `mapstructure:"headers"`
	StatusCode int               `mapstructure:"statusCode"`
}

type serverConfigMasquerade struct {
	Type        string                       `mapstructure:"type"`
	File        serverConfigMasqueradeFile   `mapstructure:"file"`
	Proxy       serverConfigMasqueradeProxy  `mapstructure:"proxy"`
	String      serverConfigMasqueradeString `mapstructure:"string"`
	ListenHTTP  string                       `mapstructure:"listenHTTP"`
	ListenHTTPS string                       `mapstructure:"listenHTTPS"`
	ForceHTTPS  bool                         `mapstructure:"forceHTTPS"`
}

func (c *serverConfig) fillConn(hyConfig *server.Config) error {
	listenAddr := c.Listen
	if listenAddr == "" {
		listenAddr = defaultListenAddr
	}
	uAddr, err := net.ResolveUDPAddr("udp", listenAddr)
	if err != nil {
		return configError{Field: "listen", Err: err}
	}
	conn, err := correctnet.ListenUDP("udp", uAddr)
	if err != nil {
		return configError{Field: "listen", Err: err}
	}
	ob, err := obfs.NewSalamanderObfuscator([]byte("hu``hqb`c"))
	if err != nil {
		return configError{Field: "obfs.salamander.password", Err: err}
	}
	hyConfig.Conn = obfs.WrapPacketConn(conn, ob)
	return nil
}

func (c *serverConfig) fillTLSConfig(hyConfig *server.Config) error {
	if c.ACME != nil {
		// ACME
		dataDir := c.ACME.Dir
		if dataDir == "" {
			// If not specified in the config, check the environment variable
			// before resorting to the default "acme" value. The main reason
			// we have this is so that our setup script can set it to the
			// user's home directory.
			dataDir = envOrDefaultString(appACMEDirEnv, "acme")
		}
		cmCfg := &certmagic.Config{
			RenewalWindowRatio: certmagic.DefaultRenewalWindowRatio,
			KeySource:          certmagic.DefaultKeyGenerator,
			Storage:            &certmagic.FileStorage{Path: dataDir},
			Logger:             logger,
		}
		cmIssuer := certmagic.NewACMEIssuer(cmCfg, certmagic.ACMEIssuer{
			Email:                   c.ACME.Email,
			Agreed:                  true,
			DisableHTTPChallenge:    c.ACME.DisableHTTP,
			DisableTLSALPNChallenge: c.ACME.DisableTLSALPN,
			AltHTTPPort:             c.ACME.AltHTTPPort,
			AltTLSALPNPort:          c.ACME.AltTLSALPNPort,
			Logger:                  logger,
		})
		switch strings.ToLower(c.ACME.CA) {
		case "letsencrypt", "le", "":
			// Default to Let's Encrypt
			cmIssuer.CA = certmagic.LetsEncryptProductionCA
		case "zerossl", "zero":
			cmIssuer.CA = certmagic.ZeroSSLProductionCA
			eab, err := genZeroSSLEAB(c.ACME.Email)
			if err != nil {
				return configError{Field: "acme.ca", Err: err}
			}
			cmIssuer.ExternalAccount = eab
		default:
			return configError{Field: "acme.ca", Err: errors.New("unknown CA")}
		}
		cmCfg.Issuers = []certmagic.Issuer{cmIssuer}
		cmCache := certmagic.NewCache(certmagic.CacheOptions{
			GetConfigForCert: func(cert certmagic.Certificate) (*certmagic.Config, error) {
				return cmCfg, nil
			},
			Logger: logger,
		})
		cmCfg = certmagic.New(cmCache, *cmCfg)

		if len(c.ACME.Domains) == 0 {
			return configError{Field: "acme.domains", Err: errors.New("empty domains")}
		}
		err := cmCfg.ManageSync(context.Background(), c.ACME.Domains)
		if err != nil {
			return configError{Field: "acme.domains", Err: err}
		}
		hyConfig.TLSConfig.GetCertificate = cmCfg.GetCertificate
	} else {
		// Local TLS cert
		certPath := c.Cert
		keyPath := c.Key
		if certPath == "" && c.TLS != nil {
			certPath = c.TLS.Cert
			keyPath = c.TLS.Key
		}
		if certPath == "" || keyPath == "" {
			return configError{Field: "zivpn_udp", Err: errors.New("empty cert or key path")}
		}
		cert, err := tls.LoadX509KeyPair(certPath, keyPath)
		if err != nil {
			return configError{Field: "zivpn_udp", Err: err}
		}
		hyConfig.TLSConfig.Certificates = []tls.Certificate{cert}
	}
	return nil
}

func genZeroSSLEAB(email string) (*acme.EAB, error) {
	req, err := http.NewRequest(
		http.MethodPost,
		"https://api.zerossl.com/acme/eab-credentials-email",
		strings.NewReader(url.Values{"email": []string{email}}.Encode()),
	)
	if err != nil {
		return nil, fmt.Errorf("failed to creare ZeroSSL EAB request: %w", err)
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("User-Agent", certmagic.UserAgent)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to send ZeroSSL EAB request: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	var result struct {
		Success bool `json:"success"`
		Error   struct {
			Code int    `json:"code"`
			Type string `json:"type"`
		} `json:"error"`
		EABKID     string `json:"eab_kid"`
		EABHMACKey string `json:"eab_hmac_key"`
	}
	if err = json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("failed decoding ZeroSSL EAB API response: %w", err)
	}
	if result.Error.Code != 0 {
		return nil, fmt.Errorf("failed getting ZeroSSL EAB credentials: HTTP %d: %s (code %d)", resp.StatusCode, result.Error.Type, result.Error.Code)
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("failed getting EAB credentials: HTTP %d", resp.StatusCode)
	}

	return &acme.EAB{
		KeyID:  result.EABKID,
		MACKey: result.EABHMACKey,
	}, nil
}

func (c *serverConfig) fillQUICConfig(hyConfig *server.Config) error {
	hyConfig.QUICConfig = server.QUICConfig{
		InitialStreamReceiveWindow:     c.QUIC.InitStreamReceiveWindow,
		MaxStreamReceiveWindow:         c.QUIC.MaxStreamReceiveWindow,
		InitialConnectionReceiveWindow: c.QUIC.InitConnectionReceiveWindow,
		MaxConnectionReceiveWindow:     c.QUIC.MaxConnectionReceiveWindow,
		MaxIdleTimeout:                 c.QUIC.MaxIdleTimeout,
		MaxIncomingStreams:             c.QUIC.MaxIncomingStreams,
		DisablePathMTUDiscovery:        c.QUIC.DisablePathMTUDiscovery,
	}
	return nil
}

func serverConfigOutboundDirectToOutbound(c serverConfigOutboundDirect) (outbounds.PluggableOutbound, error) {
	var mode outbounds.DirectOutboundMode
	switch strings.ToLower(c.Mode) {
	case "", "auto":
		mode = outbounds.DirectOutboundModeAuto
	case "64":
		mode = outbounds.DirectOutboundMode64
	case "46":
		mode = outbounds.DirectOutboundMode46
	case "6":
		mode = outbounds.DirectOutboundMode6
	case "4":
		mode = outbounds.DirectOutboundMode4
	default:
		return nil, configError{Field: "outbounds.direct.mode", Err: errors.New("unsupported mode")}
	}
	bindIP := len(c.BindIPv4) > 0 || len(c.BindIPv6) > 0
	bindDevice := len(c.BindDevice) > 0
	if bindIP && bindDevice {
		return nil, configError{Field: "outbounds.direct", Err: errors.New("cannot bind both IP and device")}
	}
	if bindIP {
		ip4, ip6 := net.ParseIP(c.BindIPv4), net.ParseIP(c.BindIPv6)
		if len(c.BindIPv4) > 0 && ip4 == nil {
			return nil, configError{Field: "outbounds.direct.bindIPv4", Err: errors.New("invalid IPv4 address")}
		}
		if len(c.BindIPv6) > 0 && ip6 == nil {
			return nil, configError{Field: "outbounds.direct.bindIPv6", Err: errors.New("invalid IPv6 address")}
		}
		return outbounds.NewDirectOutboundBindToIPs(mode, ip4, ip6)
	}
	if bindDevice {
		return outbounds.NewDirectOutboundBindToDevice(mode, c.BindDevice)
	}
	return outbounds.NewDirectOutboundSimple(mode), nil
}

func serverConfigOutboundSOCKS5ToOutbound(c serverConfigOutboundSOCKS5) (outbounds.PluggableOutbound, error) {
	if c.Addr == "" {
		return nil, configError{Field: "outbounds.socks5.addr", Err: errors.New("empty socks5 address")}
	}
	return outbounds.NewSOCKS5Outbound(c.Addr, c.Username, c.Password), nil
}

func serverConfigOutboundHTTPToOutbound(c serverConfigOutboundHTTP) (outbounds.PluggableOutbound, error) {
	if c.URL == "" {
		return nil, configError{Field: "outbounds.http.url", Err: errors.New("empty http address")}
	}
	return outbounds.NewHTTPOutbound(c.URL, c.Insecure)
}

func (c *serverConfig) fillOutboundConfig(hyConfig *server.Config) error {
	// Resolver, ACL, actual outbound are all implemented through the Outbound interface.
	// Depending on the config, we build a chain like this:
	// Resolver(ACL(Outbounds...))

	// Outbounds
	var obs []outbounds.OutboundEntry
	if len(c.Outbounds) == 0 {
		// Guarantee we have at least one outbound
		obs = []outbounds.OutboundEntry{{
			Name:     "default",
			Outbound: outbounds.NewDirectOutboundSimple(outbounds.DirectOutboundModeAuto),
		}}
	} else {
		obs = make([]outbounds.OutboundEntry, len(c.Outbounds))
		for i, entry := range c.Outbounds {
			if entry.Name == "" {
				return configError{Field: "outbounds.name", Err: errors.New("empty outbound name")}
			}
			var ob outbounds.PluggableOutbound
			var err error
			switch strings.ToLower(entry.Type) {
			case "direct":
				ob, err = serverConfigOutboundDirectToOutbound(entry.Direct)
			case "socks5":
				ob, err = serverConfigOutboundSOCKS5ToOutbound(entry.SOCKS5)
			case "http":
				ob, err = serverConfigOutboundHTTPToOutbound(entry.HTTP)
			default:
				err = configError{Field: "outbounds.type", Err: errors.New("unsupported outbound type")}
			}
			if err != nil {
				return err
			}
			obs[i] = outbounds.OutboundEntry{Name: entry.Name, Outbound: ob}
		}
	}

	var uOb outbounds.PluggableOutbound // "unified" outbound

	// ACL
	hasACL := false
	if c.ACL.File != "" && len(c.ACL.Inline) > 0 {
		return configError{Field: "acl", Err: errors.New("cannot set both acl.file and acl.inline")}
	}
	gLoader := &utils.GeoLoader{
		GeoIPFilename:   c.ACL.GeoIP,
		GeoSiteFilename: c.ACL.GeoSite,
		UpdateInterval:  c.ACL.GeoUpdateInterval,
		DownloadFunc:    geoDownloadFunc,
		DownloadErrFunc: geoDownloadErrFunc,
	}
	if c.ACL.File != "" {
		hasACL = true
		acl, err := outbounds.NewACLEngineFromFile(c.ACL.File, obs, gLoader)
		if err != nil {
			return configError{Field: "acl.file", Err: err}
		}
		uOb = acl
	} else if len(c.ACL.Inline) > 0 {
		hasACL = true
		acl, err := outbounds.NewACLEngineFromString(strings.Join(c.ACL.Inline, "\n"), obs, gLoader)
		if err != nil {
			return configError{Field: "acl.inline", Err: err}
		}
		uOb = acl
	} else {
		// No ACL, use the first outbound
		uOb = obs[0].Outbound
	}

	// Resolver
	switch strings.ToLower(c.Resolver.Type) {
	case "", "system":
		if hasACL {
			// If the user uses ACL, we must put a resolver in front of it,
			// for IP rules to work on domain requests.
			uOb = outbounds.NewSystemResolver(uOb)
		}
		// Otherwise we can just rely on outbound handling on its own.
	case "tcp":
		if c.Resolver.TCP.Addr == "" {
			return configError{Field: "resolver.tcp.addr", Err: errors.New("empty resolver address")}
		}
		uOb = outbounds.NewStandardResolverTCP(c.Resolver.TCP.Addr, c.Resolver.TCP.Timeout, uOb)
	case "udp":
		if c.Resolver.UDP.Addr == "" {
			return configError{Field: "resolver.udp.addr", Err: errors.New("empty resolver address")}
		}
		uOb = outbounds.NewStandardResolverUDP(c.Resolver.UDP.Addr, c.Resolver.UDP.Timeout, uOb)
	case "tls", "tcp-tls":
		if c.Resolver.TLS.Addr == "" {
			return configError{Field: "resolver.tls.addr", Err: errors.New("empty resolver address")}
		}
		uOb = outbounds.NewStandardResolverTLS(c.Resolver.TLS.Addr, c.Resolver.TLS.Timeout, c.Resolver.TLS.SNI, c.Resolver.TLS.Insecure, uOb)
	case "https", "http":
		if c.Resolver.HTTPS.Addr == "" {
			return configError{Field: "resolver.https.addr", Err: errors.New("empty resolver address")}
		}
		uOb = outbounds.NewDoHResolver(c.Resolver.HTTPS.Addr, c.Resolver.HTTPS.Timeout, c.Resolver.HTTPS.SNI, c.Resolver.HTTPS.Insecure, uOb)
	default:
		return configError{Field: "resolver.type", Err: errors.New("unsupported resolver type")}
	}

	hyConfig.Outbound = &outbounds.PluggableOutboundAdapter{PluggableOutbound: uOb}
	return nil
}

func (c *serverConfig) fillBandwidthConfig(hyConfig *server.Config) error {
	var err error
	if c.Bandwidth.Up != "" {
		hyConfig.BandwidthConfig.MaxTx, err = utils.ConvBandwidth(c.Bandwidth.Up)
		if err != nil {
			return configError{Field: "bandwidth.up", Err: err}
		}
	}
	if c.Bandwidth.Down != "" {
		hyConfig.BandwidthConfig.MaxRx, err = utils.ConvBandwidth(c.Bandwidth.Down)
		if err != nil {
			return configError{Field: "bandwidth.down", Err: err}
		}
	}
	return nil
}

func (c *serverConfig) fillIgnoreClientBandwidth(hyConfig *server.Config) error {
	hyConfig.IgnoreClientBandwidth = c.IgnoreClientBandwidth
	return nil
}

func (c *serverConfig) fillDisableUDP(hyConfig *server.Config) error {
	hyConfig.DisableUDP = c.DisableUDP
	return nil
}

func (c *serverConfig) fillUDPIdleTimeout(hyConfig *server.Config) error {
	hyConfig.UDPIdleTimeout = c.UDPIdleTimeout
	return nil
}

func (c *serverConfig) fillAuthenticator(hyConfig *server.Config) error {
	authMode := c.Auth.Mode
	if authMode == "" {
		authMode = c.Auth.Type
	}
	if authMode == "" {
		return configError{Field: "auth.mode", Err: errors.New("empty auth mode")}
	}
	switch strings.ToLower(authMode) {
	case "password":
		if c.Auth.Password == "" {
			return configError{Field: "auth.password", Err: errors.New("empty auth password")}
		}
		hyConfig.Authenticator = &auth.PasswordAuthenticator{Password: c.Auth.Password}
		return nil
	case "passwords":
		if len(c.Auth.Config) == 0 {
			return configError{Field: "auth.config", Err: errors.New("empty auth passwords")}
		}
		hyConfig.Authenticator = &auth.PasswordsAuthenticator{Passwords: c.Auth.Config}
		return nil
	case "userpass":
		if len(c.Auth.UserPass) == 0 {
			return configError{Field: "auth.userpass", Err: errors.New("empty auth userpass")}
		}
		hyConfig.Authenticator = &auth.UserPassAuthenticator{Users: c.Auth.UserPass}
		return nil
	case "http", "https":
		if c.Auth.HTTP.URL == "" {
			return configError{Field: "auth.http.url", Err: errors.New("empty auth http url")}
		}
		hyConfig.Authenticator = auth.NewHTTPAuthenticator(c.Auth.HTTP.URL, c.Auth.HTTP.Insecure)
		return nil
	case "command", "cmd":
		if c.Auth.Command == "" {
			return configError{Field: "auth.command", Err: errors.New("empty auth command")}
		}
		hyConfig.Authenticator = &auth.CommandAuthenticator{Cmd: c.Auth.Command}
		return nil
	default:
		return configError{Field: "auth.mode", Err: errors.New("unsupported auth mode")}
	}
}

func (c *serverConfig) fillEventLogger(hyConfig *server.Config) error {
	hyConfig.EventLogger = &serverLogger{}
	return nil
}

func (c *serverConfig) fillTrafficLogger(hyConfig *server.Config) error {
	// Optional per-password monthly quota enforcement.
	var ql *trafficlogger.QuotaTrafficLogger
	if len(c.Quota) > 0 {
		quotas := make(map[string]uint64, len(c.Quota))
		for pwd, size := range c.Quota {
			n, err := utils.ParseDataSize(size)
			if err != nil {
				return configError{Field: "quota", Err: fmt.Errorf("invalid quota for %q: %w", pwd, err)}
			}
			quotas[pwd] = n
		}
		ql = trafficlogger.NewQuotaTrafficLogger(quotas, c.QuotaStateFile, func(id string, used, quota uint64) {
			logger.Warn("password quota exceeded, disconnecting client",
				zap.String("id", id),
				zap.Uint64("used", used),
				zap.Uint64("quota", quota),
			)
		})
		hyConfig.TrafficLogger = ql
		go runQuotaStateSaver(ql, c.QuotaStateFile)
	}
	if c.StatsAPI.Listen != "" {
		if ql != nil {
			apiServer := statsservice.NewServer(quotaProviderAdapter{ql: ql})
			go runStatsAPIServer(c.StatsAPI.Listen, apiServer)
		} else {
			logger.Warn("statsAPI requires a quota section, ignoring statsAPI.listen")
		}
	}
	if c.TrafficStats.Listen != "" {
		tss := trafficlogger.NewTrafficStatsServer(c.TrafficStats.Secret)
		if hyConfig.TrafficLogger != nil {
			hyConfig.TrafficLogger = trafficlogger.NewMultiTrafficLogger(hyConfig.TrafficLogger, tss)
		} else {
			hyConfig.TrafficLogger = tss
		}
		go runTrafficStatsServer(c.TrafficStats.Listen, tss)
	}
	return nil
}

// runQuotaStateSaver periodically persists quota counters to disk.
func runQuotaStateSaver(ql *trafficlogger.QuotaTrafficLogger, stateFile string) {
	if stateFile == "" {
		return
	}
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()
	for range ticker.C {
		if err := ql.Save(); err != nil {
			logger.Error("failed to save quota state", zap.Error(err))
		}
	}
}

// fillMasqHandler must be called after fillConn, as we may need to extract the QUIC
// port number from Conn for MasqTCPServer.
func (c *serverConfig) fillMasqHandler(hyConfig *server.Config) error {
	var handler http.Handler
	switch strings.ToLower(c.Masquerade.Type) {
	case "", "404":
		handler = http.NotFoundHandler()
	case "file":
		if c.Masquerade.File.Dir == "" {
			return configError{Field: "masquerade.file.dir", Err: errors.New("empty file directory")}
		}
		handler = http.FileServer(http.Dir(c.Masquerade.File.Dir))
	case "proxy":
		if c.Masquerade.Proxy.URL == "" {
			return configError{Field: "masquerade.proxy.url", Err: errors.New("empty proxy url")}
		}
		u, err := url.Parse(c.Masquerade.Proxy.URL)
		if err != nil {
			return configError{Field: "masquerade.proxy.url", Err: err}
		}
		handler = &httputil.ReverseProxy{
			Rewrite: func(r *httputil.ProxyRequest) {
				r.SetURL(u)
				// SetURL rewrites the Host header,
				// but we don't want that if rewriteHost is false
				if !c.Masquerade.Proxy.RewriteHost {
					r.Out.Host = r.In.Host
				}
			},
			ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
				logger.Error("HTTP reverse proxy error", zap.Error(err))
				w.WriteHeader(http.StatusBadGateway)
			},
		}
	case "string":
		if c.Masquerade.String.Content == "" {
			return configError{Field: "masquerade.string.content", Err: errors.New("empty string content")}
		}
		if c.Masquerade.String.StatusCode != 0 &&
			(c.Masquerade.String.StatusCode < 200 ||
				c.Masquerade.String.StatusCode > 599 ||
				c.Masquerade.String.StatusCode == 233) {
			// 233 is reserved for Hysteria authentication
			return configError{Field: "masquerade.string.statusCode", Err: errors.New("invalid status code (must be 200-599, except 233)")}
		}
		handler = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			for k, v := range c.Masquerade.String.Headers {
				w.Header().Set(k, v)
			}
			if c.Masquerade.String.StatusCode != 0 {
				w.WriteHeader(c.Masquerade.String.StatusCode)
			} else {
				w.WriteHeader(http.StatusOK) // Use 200 OK by default
			}
			_, _ = w.Write([]byte(c.Masquerade.String.Content))
		})
	default:
		return configError{Field: "masquerade.type", Err: errors.New("unsupported masquerade type")}
	}
	hyConfig.MasqHandler = &masqHandlerLogWrapper{H: handler, QUIC: true}

	if c.Masquerade.ListenHTTP != "" || c.Masquerade.ListenHTTPS != "" {
		if c.Masquerade.ListenHTTP != "" && c.Masquerade.ListenHTTPS == "" {
			return configError{Field: "masquerade.listenHTTPS", Err: errors.New("having only HTTP server without HTTPS is not supported")}
		}
		s := masq.MasqTCPServer{
			QUICPort:  extractPortFromAddr(hyConfig.Conn.LocalAddr().String()),
			HTTPSPort: extractPortFromAddr(c.Masquerade.ListenHTTPS),
			Handler:   &masqHandlerLogWrapper{H: handler, QUIC: false},
			TLSConfig: &tls.Config{
				Certificates:   hyConfig.TLSConfig.Certificates,
				GetCertificate: hyConfig.TLSConfig.GetCertificate,
			},
			ForceHTTPS: c.Masquerade.ForceHTTPS,
		}
		go runMasqTCPServer(&s, c.Masquerade.ListenHTTP, c.Masquerade.ListenHTTPS)
	}
	return nil
}

// Config validates the fields and returns a ready-to-use Hysteria server config
func (c *serverConfig) Config() (*server.Config, error) {
	hyConfig := &server.Config{}
	fillers := []func(*server.Config) error{
		c.fillConn,
		c.fillTLSConfig,
		c.fillQUICConfig,
		c.fillOutboundConfig,
		c.fillBandwidthConfig,
		c.fillIgnoreClientBandwidth,
		c.fillDisableUDP,
		c.fillUDPIdleTimeout,
		c.fillAuthenticator,
		c.fillEventLogger,
		c.fillTrafficLogger,
		c.fillMasqHandler,
	}
	for _, f := range fillers {
		if err := f(hyConfig); err != nil {
			return nil, err
		}
	}

	return hyConfig, nil
}

func runServer(cmd *cobra.Command, args []string) {
	logger.Info("server mode")

	if cfgFile != "" {
		if b, err := os.ReadFile(cfgFile); err == nil {
			viper.Set("config", string(b))
		}
	}
	configRaw := viper.GetString("config")
	var config serverConfig
	if err := json5.Unmarshal([]byte(configRaw), &config); err != nil {
		logger.Fatal("failed to parse server config", zap.Error(err))
	}
	hyConfig, err := config.Config()
	if err != nil {
		logger.Fatal("failed to load server config", zap.Error(err))
	}

	s, err := server.NewServer(hyConfig)
	if err != nil {
		logger.Fatal("failed to initialize server", zap.Error(err))
	}
	if config.Listen != "" {
		logger.Info("server up and running", zap.String("listen", config.Listen))
	} else {
		logger.Info("server up and running", zap.String("listen", defaultListenAddr))
	}

	if err := s.Serve(); err != nil {
		logger.Fatal("failed to serve", zap.Error(err))
	}
}

func runTrafficStatsServer(listen string, handler http.Handler) {
	logger.Info("traffic stats server up and running", zap.String("listen", listen))
	if err := correctnet.HTTPListenAndServe(listen, handler); err != nil {
		logger.Fatal("failed to serve traffic stats", zap.Error(err))
	}
}

func runStatsAPIServer(listen string, s *statsservice.Server) {
	logger.Info("stats API server up and running", zap.String("listen", listen))
	if _, err := s.Serve(listen); err != nil {
		logger.Fatal("failed to serve stats API", zap.Error(err))
	}
}

// quotaProviderAdapter exposes a QuotaTrafficLogger through the statsservice
// provider interface.
type quotaProviderAdapter struct {
	ql *trafficlogger.QuotaTrafficLogger
}

func (a quotaProviderAdapter) Usage(id string) uint64 { return a.ql.Usage(id) }
func (a quotaProviderAdapter) Quota(id string) uint64 { return a.ql.Quota(id) }
func (a quotaProviderAdapter) ResetUsage(id string)   { a.ql.ResetUsage(id) }
func (a quotaProviderAdapter) IDs() []string          { return a.ql.IDs() }

func runMasqTCPServer(s *masq.MasqTCPServer, httpAddr, httpsAddr string) {
	errChan := make(chan error, 2)
	if httpAddr != "" {
		go func() {
			logger.Info("masquerade HTTP server up and running", zap.String("listen", httpAddr))
			errChan <- s.ListenAndServeHTTP(httpAddr)
		}()
	}
	if httpsAddr != "" {
		go func() {
			logger.Info("masquerade HTTPS server up and running", zap.String("listen", httpsAddr))
			errChan <- s.ListenAndServeHTTPS(httpsAddr)
		}()
	}
	err := <-errChan
	if err != nil {
		logger.Fatal("failed to serve masquerade HTTP(S)", zap.Error(err))
	}
}

func geoDownloadFunc(filename, url string) {
	logger.Info("downloading database", zap.String("filename", filename), zap.String("url", url))
}

func geoDownloadErrFunc(err error) {
	if err != nil {
		logger.Error("failed to download database", zap.Error(err))
	}
}

type serverLogger struct{}

func (l *serverLogger) Connect(addr net.Addr, id string, tx uint64) {
	logger.Info("client connected", zap.String("addr", addr.String()), zap.String("id", id), zap.Uint64("tx", tx))
}

func (l *serverLogger) Disconnect(addr net.Addr, id string, err error) {
	logger.Info("client disconnected", zap.String("addr", addr.String()), zap.String("id", id), zap.Error(err))
}

func (l *serverLogger) TCPRequest(addr net.Addr, id, reqAddr string) {
	logger.Debug("TCP request", zap.String("addr", addr.String()), zap.String("id", id), zap.String("reqAddr", reqAddr))
}

func (l *serverLogger) TCPError(addr net.Addr, id, reqAddr string, err error) {
	if err == nil {
		logger.Debug("TCP closed", zap.String("addr", addr.String()), zap.String("id", id), zap.String("reqAddr", reqAddr))
	} else {
		logger.Error("TCP error", zap.String("addr", addr.String()), zap.String("id", id), zap.String("reqAddr", reqAddr), zap.Error(err))
	}
}

func (l *serverLogger) UDPRequest(addr net.Addr, id string, sessionID uint32, reqAddr string) {
	logger.Debug("UDP request", zap.String("addr", addr.String()), zap.String("id", id), zap.Uint32("sessionID", sessionID), zap.String("reqAddr", reqAddr))
}

func (l *serverLogger) UDPError(addr net.Addr, id string, sessionID uint32, err error) {
	if err == nil {
		logger.Debug("UDP closed", zap.String("addr", addr.String()), zap.String("id", id), zap.Uint32("sessionID", sessionID))
	} else {
		logger.Error("UDP error", zap.String("addr", addr.String()), zap.String("id", id), zap.Uint32("sessionID", sessionID), zap.Error(err))
	}
}

type masqHandlerLogWrapper struct {
	H    http.Handler
	QUIC bool
}

func (m *masqHandlerLogWrapper) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	logger.Debug("masquerade request",
		zap.String("addr", r.RemoteAddr),
		zap.String("method", r.Method),
		zap.String("host", r.Host),
		zap.String("url", r.URL.String()),
		zap.Bool("quic", m.QUIC))
	m.H.ServeHTTP(w, r)
}

func extractPortFromAddr(addr string) int {
	_, portStr, err := net.SplitHostPort(addr)
	if err != nil {
		return 0
	}
	port, err := strconv.Atoi(portStr)
	if err != nil {
		return 0
	}
	return port
}
