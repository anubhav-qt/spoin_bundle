# CLIProxyAPI, which serves Gemini from the owner's Antigravity sign-ins (ADR-0106, task 0045).
# The release is pinned, and its checksum is checked against the one written here, so a
# release asset swapped after the fact fails the build instead of running.
FROM debian:bookworm-slim

ARG TARGETARCH

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl \
  && rm -rf /var/lib/apt/lists/*

# From the v8.0.23 release's checksums.txt, the version Trotter runs.
RUN set -eu; \
  case "$TARGETARCH" in \
    amd64) asset=linux_amd64; sum=744000a1a4f9ce19f5964774f853d029797b87ef53796d054389258c66cb1224 ;; \
    arm64) asset=linux_aarch64; sum=7c54c9306167b3e252090924c39a9b9dd5c09dffd376551271d8902f391f0246 ;; \
    *) echo "CLIProxyAPI has no Linux build for $TARGETARCH" >&2; exit 1 ;; \
  esac; \
  file="CLIProxyAPI_8.0.23_${asset}.tar.gz"; \
  curl -fsSL -o "/tmp/$file" "https://github.com/router-for-me/CLIProxyAPI/releases/download/v8.0.23/$file"; \
  echo "$sum  /tmp/$file" | sha256sum -c -; \
  tar -xzf "/tmp/$file" -C /usr/local/bin cli-proxy-api; \
  rm "/tmp/$file"

WORKDIR /app
COPY entrypoint.sh /usr/local/bin/cliproxy-entrypoint
RUN chmod +x /usr/local/bin/cliproxy-entrypoint

EXPOSE 8317
ENTRYPOINT ["cliproxy-entrypoint"]
