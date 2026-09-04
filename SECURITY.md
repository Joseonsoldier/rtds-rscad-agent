# Security and sensitive data

This is experimental local lab software, not a safety-certified controller. See [execution safety](docs/SAFETY.md).

Do not post API keys, credentials, proprietary manuals, project archives, uploaded document text, private rack addresses or full logs in public issues. Report a suspected vulnerability privately through the repository's GitHub Security Advisory reporting feature when enabled. If unavailable, open a minimal public issue requesting a private contact method without disclosing exploitable details or sensitive data.

Use supported Python/dependency versions and review source changes before enabling live actions. A host/OS account that can modify code, policy and manifests remains trusted; this project does not sandbox a malicious local administrator. Do not expose this STDIO service over HTTP or to untrusted remote clients.

If a key was published, revoke/rotate it before attempting repository cleanup. Removing the latest file does not remove clones, forks or historical commits. [GitHub guidance](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
