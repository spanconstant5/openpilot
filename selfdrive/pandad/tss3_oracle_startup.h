#pragma once

#include <cerrno>
#include <cstdio>
#include <fcntl.h>
#include <fstream>
#include <string>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <vector>

#include "cereal/gen/cpp/car.capnp.h"
#include "cereal/messaging/messaging.h"
#include "common/params.h"
#include "common/swaglog.h"
#include "common/timing.h"
#include "common/util.h"
#include "selfdrive/pandad/panda.h"
#include "selfdrive/pandad/tss3_startup_catcher.h"

namespace {
constexpr uint32_t TSS3_EPS_TX = 0x7A1U;
constexpr uint32_t TSS3_EPS_RX = 0x7A9U;
constexpr uint32_t TSS3_WAKE_TRIGGER_ADDR = 0x45AU;
constexpr uint8_t TSS3_DIAG_BUS = 0U;
constexpr uint64_t TSS3_EXTENDED_PERIOD_NS = 20ULL * 1000ULL * 1000ULL;
constexpr uint64_t TSS3_PREWARM_PERIOD_NS = 100ULL * 1000ULL * 1000ULL;
constexpr uint64_t TSS3_PREWARM_MAX_NS = 60ULL * 1000ULL * 1000ULL * 1000ULL;
constexpr uint64_t TSS3_WAKE_IDLE_NS = 3ULL * 1000ULL * 1000ULL * 1000ULL;
constexpr uint64_t TSS3_CATCH_TIMEOUT_NS = 2ULL * 1000ULL * 1000ULL * 1000ULL;
constexpr uint64_t TSS3_STATE_POLL_NS = 10ULL * 1000ULL * 1000ULL;
constexpr uint64_t TSS3_PARAM_POLL_NS = 250ULL * 1000ULL * 1000ULL;
constexpr char TSS3_NATIVE_CATCH_PATH[] = "/tmp/tss3-oracle-native-catch.json";
constexpr char TSS3_NATIVE_NOTIFY_PATH[] = "/tmp/tss3-oracle-native-catch.sock";
// Mirrors ToyotaSafetyFlags.TSS3 in opendbc/car/toyota/values.py. Any Toyota
// platform OpenDBC marks TSS3 sets this safety param bit, so the catcher
// follows the platform list instead of matching one car.
constexpr uint16_t TOYOTA_PARAM_TSS3 = 16U << 8;
const std::string TSS3_EXTENDED_FRAME("\x02\x10\x03\x00\x00\x00\x00\x00", 8);
const std::string TSS3_PROGRAMMING_FRAME("\x02\x10\x02\x00\x00\x00\x00\x00", 8);

class Tss3OracleStartupCatcher {
public:
  void update(Panda *panda) {
    const uint64_t now = nanos_since_boot();
    if ((now - last_param_check_ns_) >= TSS3_PARAM_POLL_NS || !param_initialized_) {
      enabled_ = tss3_auto_enabled();
      last_param_check_ns_ = now;
      param_initialized_ = true;
      if (!enabled_ && active()) {
        LOGW("TSS3 oracle startup catcher disarmed");
        state_ = ignition_initialized_ && last_ignition_ ? State::WAIT_OFF : State::DISARMED;
      }
    }

    if ((now - last_state_check_ns_) >= TSS3_STATE_POLL_NS || !ignition_initialized_) {
      last_state_check_ns_ = now;
      auto health = panda->get_state();
      if (health) {
        const bool ignition = (health->ignition_line_pkt != 0U) || (health->ignition_can_pkt != 0U);
        update_ignition(panda, ignition, now);
      }
    }

    if (state_ == State::PREWARM) {
      if ((now - wake_ns_) > TSS3_PREWARM_MAX_NS) {
        LOGW("TSS3 oracle startup prewarm reached 60 s; waiting for sleep or ignition");
        state_ = State::WAIT_SLEEP;
      } else if ((now - last_native_rx_ns_) > TSS3_WAKE_IDLE_NS) {
        LOGW("TSS3 oracle startup prewarm saw vehicle bus return quiet; re-arming");
        reset_wake_attempt();
        state_ = State::ARMED;
      } else if (now >= next_extended_tx_ns_) {
        send_extended(panda, now, TSS3_PREWARM_PERIOD_NS);
      }
    } else if (state_ == State::WAIT_SLEEP) {
      if ((now - last_native_rx_ns_) > TSS3_WAKE_IDLE_NS) {
        LOGW("TSS3 oracle startup wake interval ended; re-arming");
        reset_wake_attempt();
        state_ = State::ARMED;
      }
    } else if (state_ == State::CATCHING || state_ == State::PROGRAMMING_SENT) {
      if ((now - ignition_ns_) > TSS3_CATCH_TIMEOUT_NS) {
        LOGW("TSS3 oracle startup catcher timed out before confirmed PROGRAMMING transition");
        state_ = State::WAIT_OFF;
        return;
      }
      if (state_ == State::CATCHING && now >= next_extended_tx_ns_) {
        send_extended(panda, now, TSS3_EXTENDED_PERIOD_NS);
      }
    }
  }

  void process_rx(Panda *panda, const std::vector<can_frame> &frames) {
    for (const auto &frame : frames) {
      if (frame.src == TSS3_DIAG_BUS) {
        last_native_rx_ns_ = nanos_since_boot();
      }

      if (state_ == State::ARMED && frame.src == TSS3_DIAG_BUS && frame.address == TSS3_WAKE_TRIGGER_ADDR) {
        start_prewarm(panda, nanos_since_boot());
      }
      if (state_ == State::CATCHING && frame.address == TSS3_EPS_RX && frame.src == TSS3_DIAG_BUS &&
          is_tss3_exact_extended_response(frame.dat)) {
        const uint64_t positive_ns = nanos_since_boot();
        positive_extended_frame_ = frame.dat;
        panda->can_send(TSS3_EPS_TX, TSS3_PROGRAMMING_FRAME, TSS3_DIAG_BUS);
        const uint64_t programming_ns = nanos_since_boot();
        positive_extended_ns_ = positive_ns;
        programming_tx_ns_ = programming_ns;
        state_ = State::PROGRAMMING_SENT;
        LOGW("TSS3 oracle startup catcher sent 10 02 %.3f ms after exact positive 50 03",
             (programming_ns - positive_ns) / 1e6);
        return;
      }
      if (state_ == State::PROGRAMMING_SENT && frame.address == TSS3_EPS_RX && frame.src == TSS3_DIAG_BUS &&
          is_tss3_programming_pending_response(frame.dat)) {
        programming_response_frame_ = frame.dat;
        programming_response_ns_ = nanos_since_boot();
        if (write_marker()) {
          notify_watcher();
          state_ = State::CAUGHT;
          LOGW("TSS3 oracle startup catcher confirmed PROGRAMMING %.3f ms after 10 02",
               (programming_response_ns_ - programming_tx_ns_) / 1e6);
        } else {
          state_ = State::WAIT_OFF;
        }
        return;
      }
    }
  }

  bool active() const {
    // Pre-start states deliberately count as active so ordinary offroad safety
    // does not replace the preloaded ELM327 policy. Panda power saving remains
    // enabled through ARMED/PREWARM/WAIT_SLEEP; only the always-on main bus is
    // used until the native ignition edge.
    return state_ == State::ARMED || state_ == State::PREWARM || state_ == State::WAIT_SLEEP ||
           state_ == State::CATCHING || state_ == State::PROGRAMMING_SENT || state_ == State::CAUGHT;
  }

  bool caught() const {
    return state_ == State::CAUGHT;
  }

private:
  enum class State { DISARMED, ARMED, PREWARM, WAIT_SLEEP, CATCHING, PROGRAMMING_SENT, CAUGHT, WAIT_OFF };

  bool tss3_auto_enabled() {
    if (!params_.getBool("Tss3OracleAutoArm")) return false;
    const std::string cp_bytes = params_.get("CarParamsPersistent");
    if (cp_bytes.empty()) return false;
    try {
      AlignedBuffer aligned_buf;
      capnp::FlatArrayMessageReader cmsg(aligned_buf.align(cp_bytes.data(), cp_bytes.size()));
      const auto CP = cmsg.getRoot<cereal::CarParams>();
      const auto safety_configs = CP.getSafetyConfigs();
      if (safety_configs.size() == 0) return false;
      const bool tss3 = (safety_configs[0].getSafetyModel() == cereal::CarParams::SafetyModel::TOYOTA) &&
                        ((safety_configs[0].getSafetyParam() & TOYOTA_PARAM_TSS3) != 0U);
      if (!tss3) return false;
      fingerprint_ = CP.getCarFingerprint().cStr();
      return true;
    } catch (const kj::Exception &e) {
      LOGE("TSS3 oracle startup catcher could not parse CarParamsPersistent: %s", e.getDescription().cStr());
      return false;
    }
  }

  void update_ignition(Panda *panda, bool ignition, uint64_t now) {
    if (!ignition_initialized_) {
      ignition_initialized_ = true;
      last_ignition_ = ignition;
      if (ignition) {
        state_ = State::WAIT_OFF;
        return;
      }
      if (enabled_) arm(panda);
      return;
    }

    if (ignition && !last_ignition_ &&
        (state_ == State::ARMED || state_ == State::PREWARM || state_ == State::WAIT_SLEEP)) {
      start(panda, now);
    } else if (!ignition && last_ignition_) {
      reset_for_off();
      if (enabled_) arm(panda);
    } else if (!ignition && enabled_ && state_ == State::DISARMED) {
      arm(panda);
    } else if (ignition && enabled_ && state_ == State::DISARMED) {
      state_ = State::WAIT_OFF;
    }
    last_ignition_ = ignition;
  }

  void reset_wake_attempt() {
    wake_ns_ = 0;
    first_extended_tx_ns_ = 0;
    next_extended_tx_ns_ = 0;
    positive_extended_frame_.clear();
  }

  void reset_for_off() {
    state_ = State::DISARMED;
    ignition_ns_ = 0;
    last_native_rx_ns_ = 0;
    reset_wake_attempt();
    positive_extended_ns_ = 0;
    programming_tx_ns_ = 0;
    programming_response_ns_ = 0;
    programming_response_frame_.clear();
    first_extended_before_power_wake_ = false;
    power_wake_complete_ns_ = 0;
    std::remove(TSS3_NATIVE_CATCH_PATH);
  }

  void arm(Panda *panda) {
    std::remove(TSS3_NATIVE_CATCH_PATH);
    // Safety policy is a firmware-side filter and does not wake CAN hardware.
    // Preload it while OFF so the ignition hot path has no safety control
    // transfer ahead of the first diagnostic request.
    panda->set_safety_model(cereal::CarParams::SafetyModel::ELM327, 1U);
    // Keep explicit packet formats authoritative after CAN-FD wake traffic,
    // just as normal TSS3 safety does.
    for (uint16_t bus = 0U; bus < PANDA_CAN_CNT; bus++) {
      panda->set_can_fd_auto(bus, false);
    }
    state_ = State::ARMED;
    LOGW("TSS3 oracle startup catcher armed in Panda power-save; waiting for vehicle wake");
  }

  void start_prewarm(Panda *panda, uint64_t now) {
    std::remove(TSS3_NATIVE_CATCH_PATH);
    wake_ns_ = now;
    last_native_rx_ns_ = now;
    state_ = State::PREWARM;
    // The exact 2026 Camry proximity capture observed 0x45A as the first
    // mirrored wake frame. Logical bus 0 is Panda's always-awake main bus, so
    // offer EXTENDED at low cadence without disabling Panda power-save.
    send_extended(panda, now, TSS3_PREWARM_PERIOD_NS);
    first_extended_before_power_wake_ = true;
    LOGW("TSS3 oracle startup prewarm triggered by native bus0 0x45A");
  }

  void start(Panda *panda, uint64_t now) {
    std::remove(TSS3_NATIVE_CATCH_PATH);
    ignition_ns_ = now;
    state_ = State::CATCHING;
    // Logical bus 0 is the harness main bus and its transceiver remains enabled
    // in Panda power-save for CAN ignition detection. Queue 10 03 before the
    // control transfer that wakes the remaining transceivers.
    send_extended(panda, nanos_since_boot(), TSS3_EXTENDED_PERIOD_NS);
    first_extended_before_power_wake_ = true;
    panda->set_power_saving(false);
    power_wake_complete_ns_ = nanos_since_boot();
    LOGW("TSS3 oracle startup catcher promoted to fast catch on native ignition edge");
  }

  void send_extended(Panda *panda, uint64_t now, uint64_t period_ns) {
    panda->can_send(TSS3_EPS_TX, TSS3_EXTENDED_FRAME, TSS3_DIAG_BUS);
    const uint64_t sent_ns = nanos_since_boot();
    if (first_extended_tx_ns_ == 0) first_extended_tx_ns_ = sent_ns;
    next_extended_tx_ns_ = now + period_ns;
  }

  bool write_marker() const {
    const std::string tmp = std::string(TSS3_NATIVE_CATCH_PATH) + ".tmp";
    std::ofstream out(tmp, std::ios::trunc);
    if (!out) {
      LOGE("failed to open TSS3 native catch marker: errno=%d", errno);
      return false;
    }
    out << "{\n"
        << "  \"schema\": \"tss3-oracle-native-catch-v1\",\n"
        << "  \"target\": \"" << fingerprint_ << "\",\n"
        << "  \"pandad_wrapper_pid\": " << getppid() << ",\n"
        << "  \"wake_trigger_monotonic_ns\": " << wake_ns_ << ",\n"
        << "  \"wake_trigger_address\": " << TSS3_WAKE_TRIGGER_ADDR << ",\n"
        << "  \"ignition_monotonic_ns\": " << ignition_ns_ << ",\n"
        << "  \"first_extended_tx_monotonic_ns\": " << first_extended_tx_ns_ << ",\n"
        << "  \"positive_extended_monotonic_ns\": " << positive_extended_ns_ << ",\n"
        << "  \"positive_extended_frame_hex\": \""
        << util::hexdump(reinterpret_cast<const uint8_t *>(positive_extended_frame_.data()), positive_extended_frame_.size()) << "\",\n"
        << "  \"programming_tx_monotonic_ns\": " << programming_tx_ns_ << ",\n"
        << "  \"programming_response_monotonic_ns\": " << programming_response_ns_ << ",\n"
        << "  \"programming_response_frame_hex\": \""
        << util::hexdump(reinterpret_cast<const uint8_t *>(programming_response_frame_.data()), programming_response_frame_.size()) << "\",\n"
        << "  \"first_extended_before_power_wake\": " << (first_extended_before_power_wake_ ? "true" : "false") << ",\n"
        << "  \"power_wake_complete_monotonic_ns\": " << power_wake_complete_ns_ << ",\n"
        << "  \"programming_after_50_03_ms\": " << ((programming_tx_ns_ - positive_extended_ns_) / 1e6) << ",\n"
        << "  \"programming_response_after_10_02_ms\": " << ((programming_response_ns_ - programming_tx_ns_) / 1e6) << ",\n"
        // Preserve the kit's v1 marker contract; the response fields above add
        // proof that this request was accepted before ownership was released.
        << "  \"verdict\": \"programming_request_sent_after_exact_50_03\"\n"
        << "}\n";
    out.close();
    if (std::rename(tmp.c_str(), TSS3_NATIVE_CATCH_PATH) != 0) {
      LOGE("failed to publish TSS3 native catch marker: errno=%d", errno);
      return false;
    }
    return true;
  }

  void notify_watcher() const {
    const int fd = socket(AF_UNIX, SOCK_DGRAM, 0);
    if (fd < 0) return;
    fcntl(fd, F_SETFD, FD_CLOEXEC);
    fcntl(fd, F_SETFL, O_NONBLOCK);
    sockaddr_un addr = {};
    addr.sun_family = AF_UNIX;
    std::snprintf(addr.sun_path, sizeof(addr.sun_path), "%s", TSS3_NATIVE_NOTIFY_PATH);
    const char notification = 1;
    if (sendto(fd, &notification, sizeof(notification), 0, reinterpret_cast<sockaddr *>(&addr), sizeof(addr)) < 0) {
      LOGW("TSS3 oracle native catch notification unavailable: errno=%d", errno);
    }
    close(fd);
  }

  std::string fingerprint_;
  Params params_;
  State state_ = State::DISARMED;
  bool enabled_ = false;
  bool param_initialized_ = false;
  bool ignition_initialized_ = false;
  bool last_ignition_ = false;
  uint64_t last_param_check_ns_ = 0;
  uint64_t last_state_check_ns_ = 0;
  uint64_t wake_ns_ = 0;
  uint64_t last_native_rx_ns_ = 0;
  uint64_t ignition_ns_ = 0;
  uint64_t first_extended_tx_ns_ = 0;
  uint64_t positive_extended_ns_ = 0;
  std::string positive_extended_frame_;
  uint64_t programming_tx_ns_ = 0;
  uint64_t programming_response_ns_ = 0;
  std::string programming_response_frame_;
  uint64_t next_extended_tx_ns_ = 0;
  bool first_extended_before_power_wake_ = false;
  uint64_t power_wake_complete_ns_ = 0;
};
}  // namespace
