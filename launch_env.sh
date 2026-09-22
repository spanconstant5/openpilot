#!/usr/bin/env bash

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1

# models get lower priority than ui
# - ui is ~5ms
# - modeld is 20ms
# - DM is 10ms
# in order to run ui at 60fps (16.67ms), we need to allow
# it to preempt the model workloads. we have enough
# headroom for this until ui is moved to the CPU.
export QCOM_PRIORITY=12

if [ -z "$AGNOS_VERSION" ]; then
  export AGNOS_VERSION="19.8"
fi

export STAGING_ROOT="/data/safe_staging"

# 2025sop scaffold: force Span's Corolla TSS3 platform. carFw is incomplete (only the
# EPS record is known), so auto-fingerprint won't select it. This makes the no-SSH
# installer path work hands-off. REMOVE once full carFw is captured and fingerprinting
# resolves on its own. Actuation is still held OFF in interface.py (dashcamOnly).
export FINGERPRINT="TOYOTA_COROLLA_TSS3"
export SKIP_FW_QUERY="1"
