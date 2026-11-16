#include "selfdrive/ui/qt/widgets/tss3_oracle_control.h"

#include <QCoreApplication>
#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>

#include "cereal/messaging/messaging.h"
#include "selfdrive/ui/qt/util.h"
#include "selfdrive/ui/ui.h"

namespace {

QString oracleToolPath() {
  return QDir::cleanPath(QCoreApplication::applicationDirPath() +
                         "/../car/toyota_tss3_oracle/tss3-request-signer");
}

}  // namespace

Tss3OracleControl::Tss3OracleControl(QWidget *parent)
    : ButtonControl(
        tr("TSS3 Oracle Bringup"), tr("CHECK HARNESS"),
        tr("Install the bundled RAM-only Toyota TSS3 request signer. Keep the vehicle fully off and in Park, tap ARM, then press the brake and POWER normally. No EPS flash writes are performed."),
        parent) {
  process = new QProcess(this);
  process->setProcessChannelMode(QProcess::MergedChannels);

  QObject::connect(this, &ButtonControl::clicked, this, &Tss3OracleControl::startBringup);
  QObject::connect(process, &QProcess::readyReadStandardOutput, this, &Tss3OracleControl::handleOutput);
  QObject::connect(process, QOverload<int, QProcess::ExitStatus>::of(&QProcess::finished),
                   [this](int exitCode, QProcess::ExitStatus exitStatus) {
    handleOutput();
    if (!terminalStatus) {
      const QString detail = exitStatus == QProcess::CrashExit
        ? tr("The bringup backend crashed.")
        : tr("The bringup backend exited with status %1 without a completion report.").arg(exitCode);
      setDescription(detail);
      ConfirmationDialog::alert(tr("TSS3 Oracle Bringup Failed\n\n%1").arg(detail), this);
    }
    refresh();
  });
  QObject::connect(uiState(), &UIState::offroadTransition, this, [this](bool) { refresh(); });

  refresh();
}

void Tss3OracleControl::startBringup() {
  if (process->state() != QProcess::NotRunning) {
    if (stage == "arming" || stage == "armed") {
      QFile cancelFile(QDir(runDir).filePath("cancel-requested"));
      if (cancelFile.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
        cancelFile.write("cancel\n");
        cancelFile.close();
        setText(tr("CANCELING"));
        setDescription(tr("A cooperative cancellation was requested before PROGRAMMING."));
      } else {
        ConfirmationDialog::alert(tr("Could not request cooperative cancellation. Leave the device connected and let bringup finish."), this);
      }
    } else {
      ConfirmationDialog::alert(tr("Bringup has passed the safe cancellation point. Leave the device connected and let it finish."), this);
    }
    return;
  }

  const QString toolPath = oracleToolPath();
  if (uiState()->scene.started) {
    ConfirmationDialog::alert(tr("Turn the vehicle fully off before arming TSS3 Oracle Bringup."), this);
    return;
  }
  if (!isTss3Vehicle) {
    ConfirmationDialog::alert(tr("The saved vehicle fingerprint is not a Toyota TSS3 platform. Check the harness and complete fingerprinting first."), this);
    return;
  }
  if (!QFileInfo(toolPath).isExecutable()) {
    ConfirmationDialog::alert(tr("The bundled TSS3 oracle kit is missing or not executable."), this);
    return;
  }
  if (!ConfirmationDialog::confirm(
        tr("Keep the vehicle fully off and in Park. After tapping ARM, press the brake and POWER normally. The signer is loaded into volatile RAM only; no EPS flash writes are performed."),
        tr("ARM"), this)) {
    return;
  }

  runDir = QString("/data/tss3-oracle-runs/%1-%2-%3")
    .arg(QDateTime::currentDateTime().toString("yyyyMMddThhmmss"))
    .arg(QCoreApplication::applicationPid())
    .arg(QDateTime::currentMSecsSinceEpoch());
  if (!QDir().mkpath(runDir)) {
    ConfirmationDialog::alert(tr("Could not create the TSS3 bringup report directory."), this);
    return;
  }

  outputBuffer.clear();
  stage = "arming";
  terminalStatus = false;
  setText(tr("CANCEL"));
  setDescription(tr("Arming the startup catcher. Tap CANCEL only before PROGRAMMING."));
  process->setWorkingDirectory(QFileInfo(toolPath).absolutePath());
  process->start(toolPath, {"ui-bringup", runDir});
  if (!process->waitForStarted(1500)) {
    const QString detail = process->errorString();
    terminalStatus = true;
    setDescription(detail);
    ConfirmationDialog::alert(tr("Could not start TSS3 Oracle Bringup.\n\n%1").arg(detail), this);
    refresh();
  }
}

void Tss3OracleControl::handleOutput() {
  outputBuffer.append(process->readAllStandardOutput());
  while (true) {
    const int newline = outputBuffer.indexOf('\n');
    if (newline < 0) break;

    const QByteArray line = outputBuffer.left(newline).trimmed();
    outputBuffer.remove(0, newline + 1);
    QJsonParseError parseError;
    const QJsonDocument document = QJsonDocument::fromJson(line, &parseError);
    if (parseError.error != QJsonParseError::NoError || !document.isObject()) continue;

    const QJsonObject status = document.object();
    if (status.value("schema").toString() != "tss3-request-signer-ui-status-v1") continue;
    const QString nextStage = status.value("stage").toString();
    const QString title = status.value("title").toString();
    const QString detail = status.value("detail").toString();
    const int progress = status.value("progress").toInt(-1);
    const bool done = status.value("done").toBool(false);
    const bool error = status.value("error").toBool(false);
    if (nextStage.isEmpty() || title.isEmpty() || detail.isEmpty() || progress < 0 || progress > 100 ||
        done != (nextStage == "done") || error != (nextStage == "error")) {
      continue;
    }

    stage = nextStage;
    terminalStatus = done || error;
    setTitle(title);
    setDescription(tr("%1% — %2").arg(progress).arg(detail));
    if (done) {
      setText(tr("DONE"));
      ConfirmationDialog::alert(tr("TSS3 Oracle Bringup Complete\n\n%1").arg(detail), this);
    } else if (error) {
      setText(tr("ERROR"));
      ConfirmationDialog::alert(tr("TSS3 Oracle Bringup Failed\n\n%1").arg(detail), this);
    } else if (stage == "arming" || stage == "armed") {
      setText(tr("CANCEL"));
    } else {
      setText(tr("%1%").arg(progress));
    }
  }
}

void Tss3OracleControl::refresh() {
  isTss3Vehicle = false;
  const std::string cpBytes = params.get("CarParamsPersistent");
  if (!cpBytes.empty()) {
    AlignedBuffer alignedBuffer;
    capnp::FlatArrayMessageReader reader(alignedBuffer.align(cpBytes.data(), cpBytes.size()));
    const cereal::CarParams::Reader CP = reader.getRoot<cereal::CarParams>();
    isTss3Vehicle = CP.getBrand() == "toyota" && (CP.getFlags() & (1U << 12));
  }

  const bool toolAvailable = QFileInfo(oracleToolPath()).isExecutable();
  const bool running = process->state() != QProcess::NotRunning;
  setVisible(true);
  setEnabled(running || (!uiState()->scene.started && isTss3Vehicle && toolAvailable));
  if (!running) {
    setTitle(tr("TSS3 Oracle Bringup"));
    setText(!toolAvailable ? tr("KIT MISSING") : isTss3Vehicle ? tr("ARM") : tr("CHECK HARNESS"));
  }
}

void Tss3OracleControl::showEvent(QShowEvent *event) {
  refresh();
  ButtonControl::showEvent(event);
}
