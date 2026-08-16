package auth

import (
	"net"

	"github.com/apernet/hysteria/core/server"
)

var _ server.Authenticator = &PasswordsAuthenticator{}

// PasswordsAuthenticator checks the provided auth string against a list of
// allowed passwords.
type PasswordsAuthenticator struct {
	Passwords []string
}

func (a *PasswordsAuthenticator) Authenticate(addr net.Addr, auth string, tx uint64) (ok bool, id string) {
	for _, p := range a.Passwords {
		if auth == p {
			return true, p
		}
	}
	return false, ""
}
