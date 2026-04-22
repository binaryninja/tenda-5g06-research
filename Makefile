FIRMWARE_ZIP := 795453735379013_US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip
FIRMWARE_URL := https://static.tenda.com.cn/document/2026/04/21/ce00116cc4fa4b8ca49bac94950959a6/US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip
FIRMWARE_SHA256 := db00552932228e40d040c1765ec552e65a0da87f60e0dace40c24aa995324903
IMAGE := tenda-b104-qemu:latest
PORT ?= 18080

.PHONY: download-5g06 verify-firmware build launch-native launch-rcd logs test-config-poc test-zt-rce

download-5g06:
	mkdir -p downloads
	curl -L --fail --output downloads/$(FIRMWARE_ZIP) "$(FIRMWARE_URL)"

verify-firmware:
	printf '%s  downloads/%s\n' "$(FIRMWARE_SHA256)" "$(FIRMWARE_ZIP)" | sha256sum -c -

build:
	docker build -t $(IMAGE) .

launch-native:
	PORT=$(PORT) FIRMWARE_ARCHIVE=/firmware/downloads/$(FIRMWARE_ZIP) ./scripts/launch_native_httpd.sh

launch-rcd:
	FIRMWARE_ARCHIVE=/firmware/downloads/$(FIRMWARE_ZIP) ./scripts/launch_rcd_procd.sh

logs:
	FIRMWARE_ARCHIVE=/firmware/downloads/$(FIRMWARE_ZIP) ./scripts/stream_native_logs.sh

test-config-poc:
	python3 pocs/poc_auth_bypass_download_cfg.py --target http://127.0.0.1:$(PORT)

test-zt-rce:
	python3 pocs/poc_zerotier_unauth_rce.py --target http://127.0.0.1:$(PORT)
