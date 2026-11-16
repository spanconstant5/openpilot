#pragma once

#include <QByteArray>
#include <QString>

#include "selfdrive/ui/qt/widgets/controls.h"

class QProcess;

class Tss3OracleControl : public ButtonControl {
public:
  explicit Tss3OracleControl(QWidget *parent = nullptr);

protected:
  void showEvent(QShowEvent *event) override;

private:
  void handleOutput();
  void refresh();
  void startBringup();

  Params params;
  QProcess *process;
  QByteArray outputBuffer;
  QString runDir;
  QString stage;
  bool terminalStatus = false;
  bool isTss3Vehicle = false;
};
