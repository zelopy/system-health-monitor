import sys
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QListWidget, QListWidgetItem, QTextEdit, QPushButton, 
                           QLabel, QMessageBox, QProgressBar)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
import yaml
import paramiko
from datetime import datetime
import os
import logging

class MonitoringThread(QThread):
    """서버 모니터링을 위한 작업 스레드"""
    progress_signal = pyqtSignal(str)  # 진행 상황 시그널
    result_signal = pyqtSignal(str, dict)  # 결과 시그널 (서버이름, 결과데이터)
    finished_signal = pyqtSignal()  # 완료 시그널
    error_signal = pyqtSignal(str)  # 에러 시그널
    
    def __init__(self, server_config):
        super().__init__()
        self.server_config = server_config
        self.is_running = True
        self.ssh_connections = {}  # SSH 연결 저장용 딕셔너리
        
        # 로그 및 결과 디렉토리 설정
        self.logs_dir = self.server_config['default_settings']['logs_dir']
        self.results_dir = self.server_config['default_settings']['results_dir']
        
        # 디렉토리 생성
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.results_dir, exist_ok=True)
        
        # 로깅 설정
        self.setup_logging()

    def stop(self):
        """모니터링 중지"""
        self.is_running = False
        self.close_connections(timeout=5)
        
    def close_connections(self, timeout=None):
        """모든 SSH 연결 종료"""
        for server_name, ssh in list(self.ssh_connections.items()):
            try:
                self.logger.info(f'Closing ssh connection {server_name}')
                if timeout:
                    ssh.close(timeout=timeout)
                else:
                    ssh.close()
                del self.ssh_connections[server_name]
            except paramiko.SSHException as e:
                self.logger.error(f'SSH Connection error : {str(e)}')
            except Exception as e:
                self.logger.error(f'Unknown error : {str(e)}')

    def run(self):
        """모니터링 실행"""
        try:
            # 오늘 날짜 폴더 생성
            today_dir = os.path.join(self.results_dir, datetime.now().strftime('%Y%m%d'))
            os.makedirs(today_dir, exist_ok=True)
            
            for idx, server in enumerate(self.server_config['servers'], start=1):
                if not self.is_running:
                    break
                
                self.logger.info(f'-----------------------------------------------')
                self.logger.info(f'[ {idx} ] START ::: Checking server {server['name']}')
                self.progress_signal.emit(f"서버 {server['name']} 점검중...")
                results = self.monitor_server(server)
                if results:
                    self.current_server_name = server['name']  # 현재 서버 이름 저장
                    self.result_signal.emit(server['name'], results)
                
            self.progress_signal.emit("모니터링 완료")
            self.finished_signal.emit()
            
        except Exception as e:
            self.error_signal.emit(f"모니터링 오류: {str(e)}")
        finally:
            self.close_connections()

    def setup_logging(self):
        """로깅 설정"""
        today = datetime.now().strftime('%Y%m%d')
        log_file = os.path.join(self.logs_dir, f'monitoring_{today}.log')
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        
    def monitor_server(self, server):
        """단일 서버 모니터링"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # SSH 연결 설정
            connect_params = {
                'hostname': server['ip'],
                'username': server['username'],
                'port': server.get('port', self.server_config['default_settings']['port'])
            }
            
            if 'key_filename' in server:
                connect_params['key_filename'] = server['key_filename']
            else:
                connect_params['password'] = server['password']

            ssh.connect(**connect_params)
            self.ssh_connections[server['name']] = ssh

            # 시스템 메트릭 수집
            default_commands = {
                'cpu': "top -bn1 | grep 'Cpu(s)' | awk '{print $2}'",
                'memory': "free | grep Mem | awk '{print $3/$2 * 100.0}'",
                'disk': "df -h / | tail -1 | awk '{print $5}'",
                'load_avg': "cat /proc/loadavg | awk '{print $1, $2, $3}'",
                'uptime': "uptime -p"
            }
            
            # 서버별 개별 명령어가 있으면 추가
            commands = default_commands.copy()
            if 'commands' in server and server['commands']:
                commands.update(server['commands'])

            results = {}
            for key, cmd in commands.items():
                if not self.is_running:
                    return None
                    
                _, stdout, _ = ssh.exec_command(cmd)
                results[key] = stdout.read().decode().strip()

            # 서비스 상태 확인
            if 'services' in server:
                results['services'] = {}
                for service in server['services']:
                    service_name = service['name']
                    if service['type'] == 'systemctl':
                        _, stdout, _ = ssh.exec_command(f"systemctl is-active {service_name}")
                        status = stdout.read().decode().strip()
                        _, stdout, _ = ssh.exec_command(f"ps aux | grep -E '{service_name}' | grep -v grep | wc -l")
                        process_count = stdout.read().decode().strip()
                        results['services'][service_name] = {
                            'status': status,
                            'process_count': process_count
                        }

            # 결과 파일 생성
            today = datetime.now().strftime('%Y%m%d')
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            today_dir = os.path.join(self.results_dir, today)
            
            output_file = os.path.join(
                today_dir,
                f"{server['name']}_{server['ip']}.txt"
            )
            
            with open(output_file, 'a', encoding='utf-8') as f:
                f.write(f"=== System Monitoring at {current_time} ===\n")
                f.write(f"Server: {server['name']} ({server['ip']})\n")
                f.write(f"CPU Usage: {results['cpu']}%\n")
                f.write(f"Memory Usage: {float(results['memory']):.2f}%\n")
                f.write(f"Disk Usage: {results['disk']}\n")
                f.write(f"Load Average: {results['load_avg']}\n")
                f.write(f"Uptime: {results['uptime']}\n")
                
                # 서버별 개별 명령어 결과 기록
                if 'commands' in server:
                    f.write("\n=== Additional Checks ===\n")
                    for cmd_name, _ in server['commands'].items():
                        if cmd_name in results:
                            f.write(f"{cmd_name}: {results[cmd_name]}\n")
                    f.write("\n")
                
                if 'services' in results:
                    f.write("\n=== Service Status ===\n")
                    for service_name, service_info in results['services'].items():
                        f.write(f"{service_name}:\n")
                        f.write(f"  Status: {service_info['status']}\n")
                        f.write(f"  Process Count: {service_info['process_count']}\n")
                
                # 임계값 초과 항목이 있으면 추가 기록
                # 서버별 임계값 설정을 우선 적용, 없으면 기본 설정 사용
                default_thresholds = self.server_config['default_settings'].get('thresholds', {})
                server_thresholds = server.get('thresholds', {})
                thresholds = {**default_thresholds, **server_thresholds}  # 서버 설정으로 덮어쓰기
                
                exceeded = []
                try:
                    if float(results['cpu']) > thresholds.get('cpu', 80):
                        exceeded.append('CPU')
                    if float(results['memory']) > thresholds.get('memory', 80):
                        exceeded.append('Memory')
                    if float(results['disk'].replace('%', '')) > thresholds.get('disk', 80):
                        exceeded.append('Disk')
                        
                    if exceeded:
                        f.write("\n!!! WARNINGS !!!\n")
                        for metric in exceeded:
                            f.write(f"{metric} usage exceeds threshold!\n")
                        self.logger.warning(
                            f"[{server['name']}] Resource usage warning: "
                            f"{', '.join(exceeded)} exceeded threshold"
                        )
                except Exception as e:
                    self.logger.error(f"Error checking thresholds for server {server['name']}: {str(e)}")
                
                self.logger.info(f'END ::: Checking server {server['name']}')
                f.write("=" * 50 + "\n\n")
            return results

        except Exception as e:
            error_msg = f"{server['name']} monitoring error: {str(e)}"
            self.error_signal.emit(error_msg)
            self.logger.error(error_msg)
            return None


class ServerMonitorGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.monitoring_thread = None
        self.server_results = {}  # 서버별 결과 저장
        self.logger = logging.getLogger(__name__)
        self.initUI()
        self.load_config()

    def initUI(self):
        """UI 초기화"""
        self.setWindowTitle('서버 모니터링 시스템')
        self.setGeometry(100, 100, 1200, 800)

        # 메인 위젯 설정
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout()
        main_widget.setLayout(layout)

        # 상단 컨테이너
        top_container = QWidget()
        top_layout = QHBoxLayout()
        top_container.setLayout(top_layout)

        # 좌측 패널 (서버 목록)
        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_panel.setLayout(left_layout)
        
        left_layout.addWidget(QLabel("서버 목록"))
        self.server_list = QListWidget()
        self.server_list.itemClicked.connect(self.show_server_details)
        left_layout.addWidget(self.server_list)

        # 우측 패널 (상세 정보)
        right_panel = QWidget()
        right_layout = QVBoxLayout()
        right_panel.setLayout(right_layout)
        
        right_layout.addWidget(QLabel("상세 정보"))
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        right_layout.addWidget(self.detail_text)

        # 패널 추가
        top_layout.addWidget(left_panel, 1)
        top_layout.addWidget(right_panel, 2)

        # 하단 컨테이너
        bottom_container = QWidget()
        bottom_layout = QHBoxLayout()
        bottom_container.setLayout(bottom_layout)

        # 진행바
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 버튼
        self.start_button = QPushButton('점검 시작')
        self.start_button.clicked.connect(self.start_monitoring)
        self.stop_button = QPushButton('점검 중지')
        self.stop_button.clicked.connect(self.stop_monitoring)
        self.stop_button.setEnabled(False)
        self.exit_button = QPushButton('종료')
        self.exit_button.clicked.connect(self.close)

        bottom_layout.addWidget(self.progress_bar)
        bottom_layout.addWidget(self.start_button)
        bottom_layout.addWidget(self.stop_button)
        bottom_layout.addWidget(self.exit_button)

        # 레이아웃에 추가
        layout.addWidget(top_container)
        layout.addWidget(bottom_container)

    def load_config(self):
        """설정 파일 로드"""
        try:
            with open('servers.yaml', 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f)
                
            # 서버 목록 업데이트
            self.server_list.clear()
            for server in self.config['servers']:
                item = QListWidgetItem(server['name'])
                item.setForeground(Qt.GlobalColor.black)  # 초기 상태는 검정색
                self.server_list.addItem(item)
                
        except Exception as e:
            QMessageBox.critical(self, '오류', f'설정 파일 로드 실패: {str(e)}')

    def start_monitoring(self):
        """모니터링 시작"""
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.server_results.clear()
        self.progress_bar.setValue(0)
        
        # 서버 목록 초기화
        for i in range(self.server_list.count()):
            item = self.server_list.item(i)
            item.setText(item.text().split(' ')[-1])  # 상태 표시 제거
            item.setForeground(Qt.GlobalColor.black)  # 색상 초기화
        
        # 모니터링 스레드 생성 및 시작
        self.monitoring_thread = MonitoringThread(self.config)
        self.monitoring_thread.progress_signal.connect(self.update_progress)
        self.monitoring_thread.result_signal.connect(self.update_server_result)
        self.monitoring_thread.finished_signal.connect(self.monitoring_finished)
        self.monitoring_thread.error_signal.connect(self.show_error)
        self.monitoring_thread.start()

    def stop_monitoring(self):
        """모니터링 중지"""
        if self.monitoring_thread and self.monitoring_thread.isRunning():
            self.monitoring_thread.stop()
            if not self.monitoring_thread.wait(msecs=5000):  # 5초 timeout
                self.logger.warning("모니터링 스레드 강제 종료")
                self.monitoring_thread.terminate()  # 강제 종료
            self.monitoring_thread = None  # GC 수행되도록
            self.update_progress("모니터링 중지됨")

    def update_progress(self, message):
        """진행 상황 업데이트"""
        self.progress_bar.setFormat(message)

    def update_server_result(self, server_name, results):
        """서버 결과 업데이트"""
        self.server_results[server_name] = results
        
        # 결과에 따라 서버 목록 아이템 상태 변경
        for i in range(self.server_list.count()):
            item = self.server_list.item(i)
            base_name = item.text().split(' ')[-1]  # [완료] 또는 [이상] 제거
            
            if base_name == server_name:
                # 임계값 체크 및 상태 표시
                if self.check_thresholds(server_name, results):
                    item.setText(f"[WARNING] {server_name}")
                    item.setForeground(Qt.GlobalColor.red)
                else:
                    item.setText(f"[OK] {server_name}")
                    item.setForeground(Qt.GlobalColor.darkGreen)
                break

    def check_thresholds(self, server_name, results):
        """임계값 체크"""
        try:
            # CPU, Memory, Disk 값을 안전하게 변환
            try:
                cpu_usage = float(results['cpu'])
            except:
                cpu_usage = 0
                
            try:
                memory_usage = float(results['memory'])
            except:
                memory_usage = 0
                
            try:
                disk_usage = float(results['disk'].replace('%', ''))
            except:
                disk_usage = 0
            
            # 서버 이름으로 해당 서버의 설정 찾기
            server_config = next(
                (server for server in self.config['servers'] 
                 if server['name'] == server_name),
                None
            )
            
            # 기본 임계값 설정
            default_thresholds = self.config['default_settings']['thresholds']
            server_thresholds = server_config.get('thresholds', {})
            
            # 서버별 임계값이 있으면 적용
            if server_config and 'thresholds' in server_config:
                thresholds = {**default_thresholds, **server_thresholds}  # 서버 설정으로 덮어쓰기
            else:
                thresholds = default_thresholds
            
            return (cpu_usage > thresholds.get('cpu', 80) or
                    memory_usage > thresholds.get('memory', 80) or
                    disk_usage > thresholds.get('disk', 80))
                    
        except Exception as e:
            print(f"Failed to set thresholds: {str(e)}")
            return False

    def show_server_details(self, item):
        """서버 상세 정보 표시"""
        server_name = item.text().split(' ')[-1]  # [완료] 또는 [이상] 제거
        if server_name in self.server_results:
            results = self.server_results[server_name]
            
            # 서버 설정 찾기 (임계값 체크용)
            server_config = next(
                (server for server in self.config['servers'] 
                 if server['name'] == server_name),
                None
            )
            default_thresholds = self.config['default_settings'].get('thresholds', {})
            server_thresholds = server_config.get('thresholds', {}) if server_config else {}
            thresholds = {**default_thresholds, **server_thresholds}
                        
            details = f"<h3>=== {server_name} 상세 정보 ===</h3>"
            
            # CPU 사용률
            cpu_usage = float(results['cpu'])
            if cpu_usage > thresholds.get('cpu', 80):
                details += f'<p>CPU 사용률: <span style="color: red">{cpu_usage}%</span></p>'
            else:
                details += f'<p>CPU 사용률: {cpu_usage}%</p>'
            
            # 메모리 사용률
            memory_usage = float(results['memory'])
            if memory_usage > thresholds.get('memory', 85):
                details += f'<p>메모리 사용률: <span style="color: red">{memory_usage:.2f}%</span></p>'
            else:
                details += f'<p>메모리 사용률: {memory_usage:.2f}%</p>'
            
            # 디스크 사용률
            disk_usage = float(results['disk'].replace('%', ''))
            if disk_usage > thresholds.get('disk', 90):
                details += f'<p>디스크 사용률: <span style="color: red">{results["disk"]}</span></p>'
            else:
                details += f'<p>디스크 사용률: {results["disk"]}</p>'

            details += f'<p>부하 평균: {results["load_avg"]}</p>'
            details += f'<p>가동 시간: {results["uptime"]}</p>'
            details += '<br>'
            
            # 서버별 개별 명령어 결과 표시
            if server_config and 'commands' in server_config:
                details += f'<h4>=== 개별 점검 결과 ===</h4>'
                for cmd_name, _ in server_config['commands'].items():
                    if cmd_name in results:
                        details += f'<p><b>{cmd_name}:</b><br>'
                        details += f'&nbsp;&nbsp;결과: {results[cmd_name]}</p>'
                details += '<br>'
            
            if 'services' in results:
                details += f'<h4>=== 서비스 상태 ===</h4>'
                for service_name, service_info in results['services'].items():
                    details += f'<p><b>{service_name}:</b><br>'
                    status = service_info['status']
                    if status != 'active':
                        details += f'&nbsp;&nbsp;상태: <span style="color: red">{status}</span><br>'
                    else:
                        details += f'&nbsp;&nbsp;상태: {status}<br>'
                    details += f'&nbsp;&nbsp;프로세스 수: {service_info["process_count"]}</p>'
            
            self.detail_text.setText(details)
        else:
            self.detail_text.setText("점검 결과가 없습니다.")

    def monitoring_finished(self):
        """모니터링 완료 처리"""
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.progress_bar.setValue(100)

    def show_error(self, message):
        """에러 메시지 표시"""
        QMessageBox.warning(self, '경고', message)

    def closeEvent(self, event):
        """프로그램 종료 시 처리"""
        try:
            self.stop_monitoring()
            # 추가 정리 작업
            if hasattr(self, 'logger'):
                handlers = self.logger.handlers[:]
                for handler in handlers:
                    handler.close()
                    self.logger.removeHandler(handler)
        except Exception as e:
            self.logger.info(f'Close event error : {str(e)}')
        finally:
            event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = ServerMonitorGUI()
    ex.show()
    sys.exit(app.exec())