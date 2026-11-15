#pragma once

#include <QByteArray>
#include <QString>

#include "selfdrive/ui/qt/offroad/settings.h"

#include "frogpilot/ui/qt/offroad/frogpilot_settings.h"

class QProcess;

class DeveloperPanel : public QFrame {
  Q_OBJECT
public:
  explicit DeveloperPanel(SettingsWindow *parent);
  void showEvent(QShowEvent *event) override;

// FrogPilot variables
signals:
  void openSubPanel();
  void openSubSubPanel();

private:
  void handleTss3OracleOutput();
  void startTss3OracleBringup();
  void updateTss3OracleButton();

  Params params;
  ParamControl* adbToggle;
  ParamControl* joystickToggle;
  ParamControl* longManeuverToggle;
  ButtonControl *tss3OracleButton;
  QProcess *tss3OracleProcess;
  QByteArray tss3OracleOutputBuffer;
  QString tss3OracleRunDir;
  QString tss3OracleStage;
  bool tss3OracleTerminalStatus = false;
  bool isTss3Vehicle = false;
  bool is_release;
  bool offroad = false;

  // FrogPilot variables
  QMap<int, QString> developerMetricOptions();

  bool forceOpenDescriptions = false;

  std::map<QString, AbstractControl*> toggles;

  std::vector<QString> sidebarMetricsToggles;

  FrogPilotButtonsControl *sidebarMetricsToggle;

  FrogPilotButtonToggleControl *borderMetricsButton;

  FrogPilotManageControl *developerUIToggle;

  QSet<QString> developerMetricKeys = {"AdjacentPathMetrics", "BorderMetrics", "FPSCounter", "LeadInfo", "NumericalTemp", "SidebarMetrics", "UseSI"};
  QSet<QString> developerSidebarKeys = {"DeveloperSidebarMetric1", "DeveloperSidebarMetric2", "DeveloperSidebarMetric3", "DeveloperSidebarMetric4", "DeveloperSidebarMetric5", "DeveloperSidebarMetric6", "DeveloperSidebarMetric7"};
  QSet<QString> developerWidgetKeys = {"AdjacentLeadsUI", "RadarTracksUI", "ShowStoppingPoint"};

  QSet<QString> parentKeys;

  QStackedLayout *mainLayout;

  QWidget *mainWidget;

  ScrollView *developerMetricPanel;
  ScrollView *developerSidebarPanel;
  ScrollView *developerUIPanel;
  ScrollView *developerWidgetPanel;

private slots:
  void updateToggles(bool _offroad);
};
