#!/bin/sh
set -eu

KEY="4008dfec3c0e98c406b50f8749924008"

usage() {
    echo "Usage: $0 <encrypted-backup.bin> [output-dir]" >&2
    exit 2
}

[ "${1:-}" ] || usage

infile=$1
outdir=${2:-tmp/config_backup_decode}

[ -f "$infile" ] || {
    echo "input file not found: $infile" >&2
    exit 1
}

umask 077
mkdir -p "$outdir"

dec="$outdir/decrypted.bin"
tgz="$outdir/config.tgz"
listing="$outdir/files.txt"
extract_dir="$outdir/extracted"

openssl enc -d -aes-128-ecb -K "$KEY" -in "$infile" -out "$dec"

expected_md5=$(sed -n '1p' "$dec")
product=$(sed -n '2p' "$dec")

if [ "${#expected_md5}" -ne 32 ]; then
    echo "invalid decrypted header: first line is not a 32-byte MD5" >&2
    exit 1
fi

case "$expected_md5" in
    *[!0123456789abcdefABCDEF]*)
        echo "invalid decrypted header: first line is not hex" >&2
        exit 1
        ;;
esac

tail -n +3 "$dec" > "$tgz"

expected_md5=$(printf '%s' "$expected_md5" | tr 'A-F' 'a-f')
actual_md5=$(md5sum "$tgz" | awk '{print $1}')

if [ "$expected_md5" != "$actual_md5" ]; then
    echo "MD5 mismatch: header=$expected_md5 payload=$actual_md5" >&2
    exit 1
fi

tar -tzf "$tgz" > "$listing"
mkdir -p "$extract_dir"
tar -xzf "$tgz" -C "$extract_dir"

dec_bytes=$(wc -c < "$dec" | tr -d ' ')
tgz_bytes=$(wc -c < "$tgz" | tr -d ' ')

echo "input:      $infile"
echo "decrypted:  $dec ($dec_bytes bytes)"
echo "product:    $product"
echo "md5:        $actual_md5 verified"
echo "tarball:    $tgz ($tgz_bytes bytes)"
echo "listing:    $listing"
echo "extracted:  $extract_dir"
