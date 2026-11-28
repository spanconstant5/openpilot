#include "selfdrive/pandad/pandad.h"
#include "selfdrive/pandad/tss3_startup_catcher.h"

#include <algorithm>
#include <array>
#include <bitset>
#include <cassert>
#include <cerrno>
#include <cstdio>
#include <fcntl.h>
#include <fstream>
#include <memory>
#include <sys/socket.h>
#include <sys/un.h>
#include <thread>
#include <unistd.h>
#include <utility>

#include "cereal/gen/cpp/car.capnp.h"
#include "cereal/messaging/messaging.h"
#include "cereal/services.h"
#include "common/ratekeeper.h"
#include "common/swaglog.h"
#include "common/timing.h"
#include "common/util.h"
#include "system/hardware/hw.h"

// -- Multi-panda conventions --
// Ordering:
// - The internal panda will always be the first panda
// - Consecutive pandas will be sorted based on panda type, and then serial number
// Connecting:
// - If a panda connection is dropped, pandad will reconnect to all pandas
// - If a panda is added, we will only reconnect when we are offroad
// CAN buses:
// - Each panda will have its block of 4 buses. E.g.: the second panda will use
//   bus numbers 4, 5, 6 and 7
// - The internal panda will always be used for accessing the OBD2 port,
//   and thus firmware queries
// Safety:
// - SafetyConfig is a list, which is mapped to the connected pandas
// - If there are more pandas connected than there are SafetyConfigs,
//   the excess pandas will remain in "silent" or "noOutput" mode
// Ignition:
// - If any of the ignition sources in any panda is high, ignition is high

#define MAX_IR_PANDA_VAL 50
#define CUTOFF_IL 400
#define SATURATE_IL 1000

#define ALT_EXP_AOL_DISENGAGE_LATERAL_ON_BRAKE 2048

ExitHandler do_exit;

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
        const bool ignition = health->ignition_line_pkt || health->ignition_can_pkt;
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

bool check_all_connected(const std::vector<Panda *> &pandas) {
  for (const auto& panda : pandas) {
    if (!panda->connected()) {
      do_exit = true;
      return false;
    }
  }
  return true;
}

std::vector<const char*> filter_available_services(const std::vector<const char*> &requested, const char *context) {
  std::vector<const char*> available;
  available.reserve(requested.size());

  for (const char *name : requested) {
    if (services.count(name) > 0) {
      available.push_back(name);
    } else {
      LOGW("%s: service '%s' not found in cereal services map, disabling dependent logic", context, name);
    }
  }

  return available;
}

bool process_aol_heartbeat(SubMaster *sm, bool has_iq_state_service, bool has_car_params_service) {
  if (!has_iq_state_service || !has_car_params_service) {
    return false;
  }

  const int &alt_exp = (*sm)["carParams"].getCarParams().getAlternativeExperience();
  const bool disengage_lateral_on_brake = (alt_exp & ALT_EXP_AOL_DISENGAGE_LATERAL_ON_BRAKE) != 0;

  const bool iq_state_alive = sm->allAliveAndValid({"iqState"});
  if (!iq_state_alive) {
    return false;
  }

  const auto &aol = (*sm)["iqState"].getIqState().getAol();
  const bool heartbeat_type = disengage_lateral_on_brake ? aol.getActive() : aol.getEnabled();

  const bool engaged = iq_state_alive && heartbeat_type;

  return engaged;
}

Panda *connect(std::string serial="", uint32_t index=0) {
  std::unique_ptr<Panda> panda;
  try {
    panda = std::make_unique<Panda>(serial, (index * PANDA_BUS_OFFSET));
  } catch (std::exception &e) {
    return nullptr;
  }

  // common panda config
  if (getenv("BOARDD_LOOPBACK")) {
    panda->set_loopback(true);
  }

  for (int i = 0; i < PANDA_CAN_CNT; i++) {
    panda->set_can_fd_auto(i, true);
  }

  bool is_supported_panda = std::find(SUPPORTED_PANDA_TYPES.begin(), SUPPORTED_PANDA_TYPES.end(), panda->hw_type) != SUPPORTED_PANDA_TYPES.end();

  if (!is_supported_panda) {
    LOGW("panda %s is not supported (hw_type: %i), skipping firmware check...", panda->hw_serial().c_str(), static_cast<uint16_t>(panda->hw_type));
    return panda.release();
  }

  if (!panda->up_to_date() && !getenv("BOARDD_SKIP_FW_CHECK")) {
    throw std::runtime_error("Panda firmware out of date. Run pandad.py to update.");
  }

  return panda.release();
}

void can_send_thread(std::vector<Panda *> pandas, bool fake_send) {
  util::set_thread_name("pandad_can_send");

  AlignedBuffer aligned_buf;
  std::unique_ptr<Context> context(Context::create());
  std::unique_ptr<SubSocket> subscriber(SubSocket::create(context.get(), "sendcan", "127.0.0.1", false, true, services.at("sendcan").queue_size));
  assert(subscriber != NULL);
  subscriber->setTimeout(100);

  // run as fast as messages come in
  while (!do_exit && check_all_connected(pandas)) {
    std::unique_ptr<Message> msg(subscriber->receive());
    if (!msg) {
      continue;
    }

    capnp::FlatArrayMessageReader cmsg(aligned_buf.align(msg.get()));
    cereal::Event::Reader event = cmsg.getRoot<cereal::Event>();

    // Don't send if older than 1 second
    if ((nanos_since_boot() - event.getLogMonoTime() < 1e9) && !fake_send) {
      for (const auto& panda : pandas) {
        panda->can_send(event.getSendcan());
      }
    } else {
      LOGE("sendcan too old to send: %" PRIu64 ", %" PRIu64, nanos_since_boot(), event.getLogMonoTime());
    }
  }
}

void can_recv(std::vector<Panda *> &pandas, PubMaster *pm, Tss3OracleStartupCatcher *startup_catcher) {
  static std::vector<can_frame> raw_can_data;
  {
    bool comms_healthy = true;
    raw_can_data.clear();
    for (const auto& panda : pandas) {
      comms_healthy &= panda->can_receive(raw_can_data);
    }
    if (startup_catcher != nullptr) startup_catcher->process_rx(pandas[0], raw_can_data);

    MessageBuilder msg;
    auto evt = msg.initEvent();
    evt.setValid(comms_healthy);
    auto canData = evt.initCan(raw_can_data.size());
    for (size_t i = 0; i < raw_can_data.size(); ++i) {
      canData[i].setAddress(raw_can_data[i].address);
      canData[i].setDat(kj::arrayPtr((uint8_t*)raw_can_data[i].dat.data(), raw_can_data[i].dat.size()));
      canData[i].setSrc(raw_can_data[i].src);
    }
    pm->send("can", msg);
  }
}

void fill_panda_state(cereal::PandaState::Builder &ps, cereal::PandaState::PandaType hw_type, const health_t &health) {
  ps.setVoltage(health.voltage_pkt);
  ps.setCurrent(health.current_pkt);
  ps.setUptime(health.uptime_pkt);
  ps.setSafetyTxBlocked(health.safety_tx_blocked_pkt);
  ps.setSafetyRxInvalid(health.safety_rx_invalid_pkt);
  ps.setIgnitionLine(health.ignition_line_pkt);
  ps.setIgnitionCan(health.ignition_can_pkt);
  ps.setControlsAllowed(health.controls_allowed_pkt);
  ps.setTxBufferOverflow(health.tx_buffer_overflow_pkt);
  ps.setRxBufferOverflow(health.rx_buffer_overflow_pkt);
  ps.setPandaType(hw_type);
  ps.setSafetyModel(cereal::CarParams::SafetyModel(health.safety_mode_pkt));
  ps.setSafetyParam(health.safety_param_pkt);
  ps.setFaultStatus(cereal::PandaState::FaultStatus(health.fault_status_pkt));
  ps.setPowerSaveEnabled((bool)(health.power_save_enabled_pkt));
  ps.setHeartbeatLost((bool)(health.heartbeat_lost_pkt));
  ps.setAlternativeExperience(health.alternative_experience_pkt);
  ps.setHarnessStatus(cereal::PandaState::HarnessStatus(health.car_harness_status_pkt));
  ps.setInterruptLoad(health.interrupt_load_pkt);
  ps.setFanPower(health.fan_power);
  ps.setSafetyRxChecksInvalid((bool)(health.safety_rx_checks_invalid_pkt));
  ps.setSpiErrorCount(health.spi_error_count_pkt);
  ps.setSbu1Voltage(health.sbu1_voltage_mV / 1000.0f);
  ps.setSbu2Voltage(health.sbu2_voltage_mV / 1000.0f);
}

void fill_panda_can_state(cereal::PandaState::PandaCanState::Builder &cs, const can_health_t &can_health) {
  cs.setBusOff((bool)can_health.bus_off);
  cs.setBusOffCnt(can_health.bus_off_cnt);
  cs.setErrorWarning((bool)can_health.error_warning);
  cs.setErrorPassive((bool)can_health.error_passive);
  cs.setLastError(cereal::PandaState::PandaCanState::LecErrorCode(can_health.last_error));
  cs.setLastStoredError(cereal::PandaState::PandaCanState::LecErrorCode(can_health.last_stored_error));
  cs.setLastDataError(cereal::PandaState::PandaCanState::LecErrorCode(can_health.last_data_error));
  cs.setLastDataStoredError(cereal::PandaState::PandaCanState::LecErrorCode(can_health.last_data_stored_error));
  cs.setReceiveErrorCnt(can_health.receive_error_cnt);
  cs.setTransmitErrorCnt(can_health.transmit_error_cnt);
  cs.setTotalErrorCnt(can_health.total_error_cnt);
  cs.setTotalTxLostCnt(can_health.total_tx_lost_cnt);
  cs.setTotalRxLostCnt(can_health.total_rx_lost_cnt);
  cs.setTotalTxCnt(can_health.total_tx_cnt);
  cs.setTotalRxCnt(can_health.total_rx_cnt);
  cs.setTotalFwdCnt(can_health.total_fwd_cnt);
  cs.setCanSpeed(can_health.can_speed);
  cs.setCanDataSpeed(can_health.can_data_speed);
  cs.setCanfdEnabled(can_health.canfd_enabled);
  cs.setBrsEnabled(can_health.brs_enabled);
  cs.setCanfdNonIso(can_health.canfd_non_iso);
  cs.setIrq0CallRate(can_health.irq0_call_rate);
  cs.setIrq1CallRate(can_health.irq1_call_rate);
  cs.setIrq2CallRate(can_health.irq2_call_rate);
  cs.setCanCoreResetCnt(can_health.can_core_reset_cnt);
}

std::optional<bool> send_panda_states(PubMaster *pm, const std::vector<Panda *> &pandas, bool is_onroad,
                                      bool spoofing_started, bool always_offroad, bool startup_catcher_active) {
  bool ignition_local = false;
  const uint32_t pandas_cnt = pandas.size();
  static Params params;
  const bool allow_offroad_external_can_tx = params.getBool("Konn3ktAllowOffroadExternalCanTx");

  // build msg
  MessageBuilder msg;
  auto evt = msg.initEvent();
  auto pss = evt.initPandaStates(pandas_cnt);

  std::vector<health_t> pandaStates;
  pandaStates.reserve(pandas_cnt);

  std::vector<std::array<can_health_t, PANDA_CAN_CNT>> pandaCanStates;
  pandaCanStates.reserve(pandas_cnt);

  const bool red_panda_comma_three = (pandas.size() == 2) &&
                                     (pandas[0]->hw_type == cereal::PandaState::PandaType::DOS) &&
                                     (pandas[1]->hw_type == cereal::PandaState::PandaType::RED_PANDA);

  for (const auto& panda : pandas){
    auto health_opt = panda->get_state();
    if (!health_opt) {
      return std::nullopt;
    }

    health_t health = *health_opt;

    std::array<can_health_t, PANDA_CAN_CNT> can_health{};
    for (uint32_t i = 0; i < PANDA_CAN_CNT; i++) {
      auto can_health_opt = panda->get_can_state(i);
      if (!can_health_opt) {
        return std::nullopt;
      }
      can_health[i] = *can_health_opt;
    }
    pandaCanStates.push_back(can_health);

    if (spoofing_started) {
      health.ignition_line_pkt = 1;
    }

    // on comma three setups with a red panda, the dos can
    // get false positive ignitions due to the harness box
    // without a harness connector, so ignore it
    if (red_panda_comma_three && (panda->hw_type == cereal::PandaState::PandaType::DOS)) {
      health.ignition_line_pkt = 0;
    }

    // Keep physical ignition detection independent from always_offroad mode.
    // always_offroad should affect safety/onroad state, not force panda low-power.
    ignition_local |= ((health.ignition_line_pkt != 0) || (health.ignition_can_pkt != 0));

    pandaStates.push_back(health);
  }

  for (uint32_t i = 0; i < pandas_cnt; i++) {
    auto panda = pandas[i];
    const auto &health = pandaStates[i];

    // Make sure CAN buses are live: safety_setter_thread does not work if Panda CAN are silent and there is only one other CAN node
    if (health.safety_mode_pkt == (uint8_t)(cereal::CarParams::SafetyModel::SILENT)) {
      panda->set_safety_model(cereal::CarParams::SafetyModel::NO_OUTPUT);
    }

    const bool allow_external_tx_now = allow_offroad_external_can_tx && !is_onroad;

    bool power_save_desired = allow_external_tx_now ? false : !ignition_local;
    if (health.power_save_enabled_pkt != power_save_desired) {
      panda->set_power_saving(power_save_desired);
    }

    if (allow_external_tx_now && (health.safety_mode_pkt != (uint8_t)(cereal::CarParams::SafetyModel::ALL_OUTPUT))) {
      panda->set_safety_model(cereal::CarParams::SafetyModel::ALL_OUTPUT);
    }

    bool should_close_relay = (!ignition_local || !is_onroad) && !allow_external_tx_now;
    if (!startup_catcher_active && should_close_relay &&
        (health.safety_mode_pkt != (uint8_t)(cereal::CarParams::SafetyModel::NO_OUTPUT))) {
      panda->set_safety_model(cereal::CarParams::SafetyModel::NO_OUTPUT);
    }

    if (!panda->comms_healthy()) {
      evt.setValid(false);
    }

    auto ps = pss[i];
    fill_panda_state(ps, panda->hw_type, health);

    auto cs = std::array{ps.initCanState0(), ps.initCanState1(), ps.initCanState2()};
    for (uint32_t j = 0; j < PANDA_CAN_CNT; j++) {
      fill_panda_can_state(cs[j], pandaCanStates[i][j]);
    }

    // Convert faults bitset to capnp list
    // bits above the last named fault type would leave unset list entries, which read as relayMalfunction
    std::bitset<sizeof(health.faults_pkt) * 8> fault_bits(health.faults_pkt & ((2U << size_t(cereal::PandaState::FaultType::INTERRUPT_RATE_SOUND_DMA)) - 1U));
    auto faults = ps.initFaults(fault_bits.count());

    size_t j = 0;
    for (size_t f = size_t(cereal::PandaState::FaultType::RELAY_MALFUNCTION);
         f <= size_t(cereal::PandaState::FaultType::INTERRUPT_RATE_SOUND_DMA); f++) {
      if (fault_bits.test(f)) {
        faults.set(j, cereal::PandaState::FaultType(f));
        j++;
      }
    }
  }

  pm->send("pandaStates", msg);
  return ignition_local;
}

void send_peripheral_state(Panda *panda, PubMaster *pm) {
  // build msg
  MessageBuilder msg;
  auto evt = msg.initEvent();
  evt.setValid(panda->comms_healthy());

  auto ps = evt.initPeripheralState();
  ps.setPandaType(panda->hw_type);

  double read_time = millis_since_boot();
  ps.setVoltage(Hardware::get_voltage());
  ps.setCurrent(Hardware::get_current());
  read_time = millis_since_boot() - read_time;
  if (read_time > 50) {
    LOGW("reading hwmon took %lfms", read_time);
  }

  // fall back to panda's voltage and current measurement
  if (ps.getVoltage() == 0 && ps.getCurrent() == 0) {
    auto health_opt = panda->get_state();
    if (health_opt) {
      health_t health = *health_opt;
      ps.setVoltage(health.voltage_pkt);
      ps.setCurrent(health.current_pkt);
    }
  }

  uint16_t fan_speed_rpm = panda->get_fan_speed();
  ps.setFanSpeedRpm(fan_speed_rpm);

  pm->send("peripheralState", msg);
}

void process_panda_state(std::vector<Panda *> &pandas, PubMaster *pm, bool engaged, bool engaged_aol,
                         bool is_onroad, bool spoofing_started, bool always_offroad, bool startup_catcher_active) {
  std::vector<std::string> connected_serials;
  for (Panda *p : pandas) {
    connected_serials.push_back(p->hw_serial());
  }

  {
    auto ignition_opt = send_panda_states(pm, pandas, is_onroad, spoofing_started, always_offroad, startup_catcher_active);
    if (!ignition_opt) {
      LOGE("Failed to get ignition_opt");
      return;
    }

    // check if we should have pandad reconnect
    if (!ignition_opt.value()) {
      bool comms_healthy = true;
      for (const auto &panda : pandas) {
        comms_healthy &= panda->comms_healthy();
      }

      if (!comms_healthy) {
        LOGE("Reconnecting, communication to pandas not healthy");
        do_exit = true;

      } else {
        // check for new pandas
        for (std::string &s : Panda::list(true)) {
          if (!std::count(connected_serials.begin(), connected_serials.end(), s)) {
            LOGW("Reconnecting to new panda: %s", s.c_str());
            do_exit = true;
            break;
          }
        }
      }
    }

    for (const auto &panda : pandas) {
      panda->send_heartbeat(engaged, engaged_aol);
    }
  }
}

void process_peripheral_state(Panda *panda, PubMaster *pm, bool no_fan_control) {
  static Params params;
  static const bool has_device_state = services.count("deviceState") > 0;
  static const bool has_driver_camera_state = services.count("driverCameraState") > 0;
  static std::vector<const char*> sm_services = filter_available_services({"deviceState", "driverCameraState"}, "pandad peripheral");
  static std::unique_ptr<SubMaster> sm = sm_services.empty() ? nullptr : std::make_unique<SubMaster>(sm_services);

  static uint64_t last_driver_camera_t = 0;
  static uint16_t prev_fan_speed = 999;
  static int ir_pwr = 0;
  static int prev_ir_pwr = 999;
  static uint32_t prev_frame_id = UINT32_MAX;
  static bool driver_view = false;

  // TODO: can we merge these?
  static FirstOrderFilter integ_lines_filter(0, 30.0, 0.05);
  static FirstOrderFilter integ_lines_filter_driver_view(0, 5.0, 0.05);

  {
    if (sm != nullptr) {
      sm->update(0);
    }

    if (sm != nullptr && has_device_state && sm->updated("deviceState") && !no_fan_control) {
      // Fan speed
      uint16_t fan_speed = (*sm)["deviceState"].getDeviceState().getFanSpeedPercentDesired();
      if (fan_speed != prev_fan_speed || sm->frame % 100 == 0) {
        panda->set_fan_speed(fan_speed);
        prev_fan_speed = fan_speed;
      }
    }

    if (sm != nullptr && has_driver_camera_state && sm->updated("driverCameraState")) {
      auto event = (*sm)["driverCameraState"];
      int cur_integ_lines = event.getDriverCameraState().getIntegLines();

      // reset the filter when camerad restarts
      if (event.getDriverCameraState().getFrameId() < prev_frame_id) {
        integ_lines_filter.reset(0);
        integ_lines_filter_driver_view.reset(0);
        driver_view = params.getBool("IsDriverViewEnabled");
      }
      prev_frame_id = event.getDriverCameraState().getFrameId();

      cur_integ_lines = (driver_view ? integ_lines_filter_driver_view : integ_lines_filter).update(cur_integ_lines);
      last_driver_camera_t = event.getLogMonoTime();

      if (cur_integ_lines <= CUTOFF_IL) {
        ir_pwr = 0;
      } else if (cur_integ_lines > SATURATE_IL) {
        ir_pwr = 100;
      } else {
        ir_pwr = 100 * (cur_integ_lines - CUTOFF_IL) / (SATURATE_IL - CUTOFF_IL);
      }
    }

    // Disable IR on input timeout
    if (nanos_since_boot() - last_driver_camera_t > 1e9) {
      ir_pwr = 0;
    }

    int frame = sm != nullptr ? sm->frame : 0;
    if (ir_pwr != prev_ir_pwr || frame % 100 == 0) {
      int16_t ir_panda = util::map_val(ir_pwr, 0, 100, 0, MAX_IR_PANDA_VAL);
      panda->set_ir_pwr(ir_panda);
      Hardware::set_ir_power(ir_pwr);
      prev_ir_pwr = ir_pwr;
    }
  }
}

bool pandad_run(std::vector<Panda *> &pandas) {
  const bool no_fan_control = getenv("NO_FAN_CONTROL") != nullptr;
  const bool spoofing_started = getenv("STARTED") != nullptr;
  const bool fake_send = getenv("FAKESEND") != nullptr;

  // Start the CAN send thread
  std::thread send_thread(can_send_thread, pandas, fake_send);

  Params params;
  RateKeeper rk("pandad", 100);
  const bool has_car_params_service = services.count("carParams") > 0;
  const bool has_selfdrive_state_service = services.count("selfdriveState") > 0;
  const bool has_iq_state_service = services.count("iqState") > 0;
  std::vector<const char*> sm_services = filter_available_services({"selfdriveState", "carParams", "iqState"}, "pandad main");
  std::unique_ptr<SubMaster> sm = sm_services.empty() ? nullptr : std::make_unique<SubMaster>(sm_services);
  if (!has_iq_state_service) {
    LOGW("iqState service not found in cereal services map; steering guidance heartbeat disabled");
  }
  PubMaster pm({"can", "pandaStates", "peripheralState"});
  PandaSafety panda_safety(pandas);
  Panda *peripheral_panda = pandas[0];
  Tss3OracleStartupCatcher tss3_startup_catcher;
  bool engaged = false;
  bool engaged_aol = false;
  bool is_onroad = false;
  bool always_offroad = false;
  bool oracle_handoff = false;

  // Main loop: receive CAN data and process states
  while (!do_exit && check_all_connected(pandas)) {
    tss3_startup_catcher.update(peripheral_panda);
    can_recv(pandas, &pm, &tss3_startup_catcher);
    if (tss3_startup_catcher.caught()) {
      oracle_handoff = true;
      do_exit = true;
      break;
    }

    // Process peripheral state at 20 Hz
    if (rk.frame() % 5 == 0) {
      process_peripheral_state(peripheral_panda, &pm, no_fan_control);
    }

    // Process panda state at 10 Hz
    if (rk.frame() % 10 == 0) {
      if (sm != nullptr) {
        sm->update(0);
      }
      engaged = (sm != nullptr) && has_selfdrive_state_service &&
                sm->allAliveAndValid({"selfdriveState"}) && (*sm)["selfdriveState"].getSelfdriveState().getEnabled();
      engaged_aol = (sm != nullptr) ? process_aol_heartbeat(sm.get(), has_iq_state_service, has_car_params_service) : false;
      is_onroad = params.getBool("IsOnroad");
      always_offroad = panda_safety.getOffroadMode();
      process_panda_state(pandas, &pm, engaged, engaged_aol, is_onroad, spoofing_started,
                          always_offroad, tss3_startup_catcher.active());
      if (should_configure_panda_safety(is_onroad, tss3_startup_catcher.active())) {
        panda_safety.configureSafetyMode(is_onroad);
      }
    }

    // Send out peripheralState at 2Hz
    if (rk.frame() % 50 == 0) {
      send_peripheral_state(peripheral_panda, &pm);
    }

    // Forward logs from pandas to cloudlog if available
    for (auto *panda : pandas) {
      std::string log = panda->serial_read();
      if (!log.empty()) {
        if (log.find("Register 0x") != std::string::npos) {
          // Log register divergent faults as errors
          LOGE("%s", log.c_str());
        } else {
          LOGD("%s", log.c_str());
        }
      }
    }

    rk.keepTime();
  }

  // Close relay on exit to prevent a fault
  if (!oracle_handoff && is_onroad && !engaged) {
    for (auto &p : pandas) {
      if (p->connected()) {
        p->set_safety_model(cereal::CarParams::SafetyModel::NO_OUTPUT);
      }
    }
  }

  send_thread.join();
  return oracle_handoff;
}

int pandad_main_thread(std::vector<std::string> serials) {
  if (serials.size() == 0) {
    serials = Panda::list();

    if (serials.size() == 0) {
      LOGW("no pandas found, exiting");
      return 0;
    }
  }

  std::string serials_str;
  for (int i = 0; i < serials.size(); i++) {
    serials_str += serials[i];
    if (i < serials.size() - 1) serials_str += ", ";
  }
  LOGW("connecting to pandas: %s", serials_str.c_str());

  // connect to all provided serials
  std::vector<Panda *> pandas;
  for (int i = 0; i < serials.size() && !do_exit; /**/) {
    Panda *p = connect(serials[i], i);
    if (!p) {
      util::sleep_for(100);
      continue;
    }

    pandas.push_back(p);
    ++i;
  }

  bool oracle_handoff = false;
  if (!do_exit) {
    LOGW("connected to all pandas");
    oracle_handoff = pandad_run(pandas);
  }

  for (Panda *panda : pandas) {
    delete panda;
  }
  return oracle_handoff ? TSS3_ORACLE_HANDOFF_EXIT_CODE : 0;
}
