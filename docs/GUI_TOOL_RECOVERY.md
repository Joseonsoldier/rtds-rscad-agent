# GUI tool recovery and local verification

2026-09-05. The initialization failure is repaired in the same task with the existing installation-root workspace. Moving the project folder is no longer required.

## Cause and authorized repair

Minimal node_repl JavaScript previously failed before execution. The sandbox log identified SetNamedSecurityInfoW failed: 5 while provisioning permissions on the administrator-owned installation root. Repository-scoped official sandbox probes passed, but the current task still included that root. This was a host ACL provisioning failure.

After the user's explicit folder-permission request, Windows UAC approval was used to run native icacls once. The manual change grants the current user WRITE_DAC (permission to modify the folder DACL) on the installation root only, with no inheritance or recursive command. Exit code was 0. Ownership remains Administrators. This persistent permission change does not elevate the ongoing Codex or RSCAD process. Original ACL and post-command SDDL were backed up. Subsequent normal Codex provisioning added its sandbox entries, including inheritable entries; this report therefore does not claim all descendant ACLs stayed unchanged. No sandbox mode, firewall, Defender, execution policy or product execution grants changed.

## Actual verification

- Actual node_repl reset, minimal execution, @oai/sky import and returned-window enumeration passed in the same task.
- The returned RSCAD FX 2.7 window was activated; its foreground screenshot and accessibility tree were observed successfully.
- The exact previously saved isolated script_example.rtfx path was entered in Open Resource File. Opening it displayed the script_example tab, Draft / SS #1 and Chapter #7 tutorial circuit. This binds this controlled GUI open to the prepared saved copy; it is not general discovery of arbitrary pre-existing projects.
- Only the owned script_example tab was closed. The pre-existing Untitled tab remained, with no save prompt or extra save.
- All 70 protected original/SDK/document/definition/data hashes match. The saved trial model retains its pre-GUI SHA-256 hash.

No rack query/reservation/connection, Compile, Runtime action, parameter edit or structural mutation was issued. Cached rack status was incidentally visible; no rack-pane action was taken. Separate Java background traffic was not measured.

## Remaining limitations

An occluded-window capture displayed unrelated foreground content and was rejected as RSCAD evidence. Activating the exact returned RSCAD window before capture produced the correct screen. Occluded capture is not qualified on this host. A modal accessibility index was reported unavailable and the structured focused element was stale; fresh screenshot coordinates and the visible filename caret allowed the scoped Open operation. Do not reuse stale indexes or label these plugin limitations fixed by the ACL repair.

EXT-02 now has one actual foreground GUI project-open/close observation alongside earlier SDK case/Draft identity. General GUI/session discovery, unsaved-state discovery, live Runtime target identification and rack validation remain unqualified. Previous SDK round trips and unit-test counts remain separate historical results. No production code, package dependency or public contract changed for this repair; unit tests were not rerun for documentation-only changes.

Private evidence: ignored .validation/gui-repair-20260905 contains acl-before.json, acl-apply-result.json, acl-gui-verification.json and observed open/closed accessibility trees. Earlier diagnosis and failed probes are historical, not current status. Do not blindly restore the entire old ACL: it predates normal sandbox entries and would reintroduce the failure.

Official background: [Windows sandbox troubleshooting](https://learn.chatgpt.com/docs/windows/windows-sandbox) and [permission profiles](https://learn.chatgpt.com/docs/permissions). The specific diagnosis, repair and GUI results above are local observations.
