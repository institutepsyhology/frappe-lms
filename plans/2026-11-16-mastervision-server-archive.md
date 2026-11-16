# Run Master Vision account collection beside MVC

The owner requests parallel MV collection with immediate delivery to MV Frappe.
At inspection the laptop had about 175 MiB free RAM; the server had about 1.9 GiB
available RAM, 7.7 GiB disk and low load. Run the new job entirely on the server,
without restarting, slowing or changing the running MVC processes. Begin at one
request/second and compare MVC's observed throughput after starting MV.

Use the already tested source collector with one immutable allowlisted account
profile selected before imports in a dedicated process. MVC defaults, formats,
Windows DPAPI namespace and the self-contained receiver remain compatible with
the running job. MV uses only shop.mastervision.su (its API responds HTTP 401
without a key), my-lk.mastervision.su, distinct schemas/namespaces and an existing
MV site key for server encryption. Reject unknown/mixed account identities.

Keep the full encrypted source archive directly under the MV site's private
directory. There is no laptop payload spool and no second archive transfer copy.
Use the existing source logs, resume cursor and ten-error stop rules. Retain
raw list URLs as untrusted; verify personal URLs from individual cards.

The local masked launcher sends the MV GET key through authenticated SSH stdin.
The remote launcher passes it through a pipe to a detached worker; no secret
arguments, environment variables, files or logs. Verify published source hashes
before launch, an MV site key, a single-worker lock and the exact profile before
accepting the key. A lost API key on process/container restart needs new entry.

Test account isolation in fresh processes, default MVC regressions, Linux cipher
binding, masked-key transport, detached start/duplicate rejection and safe failure
reporting. Publish the tested source, install a versioned private program bundle,
verify its hashes, then open the key window. Check real MV saves and unchanged
MVC throughput before reporting that both jobs run successfully. This retains
source data on Frappe's server; it does not yet create all LMS users or activate
the separate legacy-link authentication feature.
