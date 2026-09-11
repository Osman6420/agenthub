#!/bin/sh
set -eu

uid=$(id -u)
gid=$(id -g)

if ! getent passwd "$uid" >/dev/null 2>&1; then
    passwd_file=/tmp/agenthub-passwd
    group_file=/tmp/agenthub-group
    cp /etc/passwd "$passwd_file"
    cp /etc/group "$group_file"
    printf 'agenthub-postgres:x:%s:%s:AgentHub PostgreSQL:/tmp:/sbin/nologin\n' \
        "$uid" "$gid" >> "$passwd_file"
    if ! getent group "$gid" >/dev/null 2>&1; then
        printf 'agenthub-postgres:x:%s:\n' "$gid" >> "$group_file"
    fi
    wrapper=$(find /usr/lib -name libnss_wrapper.so -type f -print -quit)
    [ -n "$wrapper" ] || {
        printf 'libnss_wrapper is unavailable\n' >&2
        exit 1
    }
    export NSS_WRAPPER_PASSWD="$passwd_file"
    export NSS_WRAPPER_GROUP="$group_file"
    export LD_PRELOAD="${LD_PRELOAD:+$LD_PRELOAD:}$wrapper"
fi

exec /usr/local/bin/docker-entrypoint.sh "$@"
