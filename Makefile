# StartOS 0.4.x package for TailWatcher.
#
#   make            # docker build + pack → tailwatcher_x86_64.s9pk
#   make install    # sideload the .s9pk to the host in ~/.startos/config.yaml
#   make test       # run the watcher's unit tests

IMAGE := start9/tailwatcher/main:0.19.1
ARCHES := x86 arm
TARGETS := x86

.PHONY: image test

include s9pk.mk

image:
	docker build --network=host -t $(IMAGE) .

test:
	cd app && python3 -m unittest -v test_tailwatcher test_commands test_flights test_lookup test_trips test_web test_edits test_ntfy_admin test_invites test_itinerary

# The manifest points at the local $(IMAGE) tag, so build it before packing.
# `make arm` only works on an arm64 machine (the release workflow's arm runner).
$(BASE_NAME)_x86_64.s9pk: image
$(BASE_NAME)_aarch64.s9pk: image
