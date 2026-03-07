"""Lean Docker 실행기

Docker 컨테이너로 Lean 백테스트 직접 실행. (Lean CLI 불필요)
"""

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .project_manager import LeanProject

logger = logging.getLogger(__name__)

# Lean Docker 이미지
LEAN_IMAGE = "quantconnect/lean:latest"

# DooD (Docker-out-of-Docker) 모드: 컨테이너 안에서 sibling 컨테이너를 스폰할 때 사용
# 설정되면 바인드 마운트 대신 네임드 볼륨을 사용하여 Lean 컨테이너에 데이터를 전달
LEAN_DOCKER_VOLUME_NAME = os.environ.get("LEAN_DOCKER_VOLUME_NAME")
LEAN_WORKSPACE_MOUNT = Path("/app/.lean-workspace")


@dataclass
class LeanRun:
    """Lean 백테스트 실행 결과"""
    project: LeanProject
    success: bool
    output_dir: Path
    raw_result: Optional[Dict] = None
    error: Optional[str] = None
    duration_seconds: float = 0
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: Optional[datetime] = None
    
    @property
    def result_json(self) -> Optional[Path]:
        """결과 JSON 파일 경로"""
        if not self.output_dir.exists():
            return None
        
        # Algorithm.json이 메인 결과 파일
        main_result = self.output_dir / "Algorithm.json"
        if main_result.exists():
            return main_result
        
        # 폴백: order, log, summary, monitor 제외한 첫 번째 json
        for f in self.output_dir.glob("*.json"):
            name_lower = f.name.lower()
            if not any(x in name_lower for x in ["order", "log", "summary", "monitor"]):
                return f
        
        return None
    
    @property
    def orders_json(self) -> Optional[Path]:
        """주문 내역 JSON 파일 경로"""
        if not self.output_dir.exists():
            return None
        
        for f in self.output_dir.glob("*order*.json"):
            return f
        
        return None
    
    @property
    def log_txt(self) -> Optional[Path]:
        """로그 파일 경로"""
        if not self.output_dir.exists():
            return None
        
        for f in self.output_dir.glob("*.log"):
            return f
        for f in self.output_dir.glob("*log*.txt"):
            return f
        
        return None
    
    def load_result(self) -> Dict:
        """결과 JSON 로드"""
        if self.raw_result:
            return self.raw_result
        
        result_file = self.result_json
        if result_file and result_file.exists():
            self.raw_result = json.loads(result_file.read_text())
            return self.raw_result
        
        return {}
    
    def get_statistics(self) -> Dict[str, Any]:
        """통계 추출"""
        result = self.load_result()
        return result.get("statistics", {})
    
    def get_trades(self) -> List[Dict]:
        """거래 내역 추출"""
        result = self.load_result()
        orders = result.get("orders", {})
        return list(orders.values()) if isinstance(orders, dict) else []
    
    def get_equity_curve(self) -> Dict[str, float]:
        """자산 곡선 추출"""
        result = self.load_result()
        charts = result.get("charts", {})
        
        strategy_equity = charts.get("Strategy Equity", {})
        series = strategy_equity.get("series", {})
        equity_series = series.get("Equity", {})
        values = equity_series.get("values", [])
        
        # Lean format: [timestamp, open, high, low, close]
        return {
            str(point[0]): point[4] if len(point) > 4 else point[1]
            for point in values if isinstance(point, list) and len(point) >= 2
        }


class LeanExecutor:
    """Lean Docker 실행기 (Lean CLI 불필요)"""
    
    @classmethod
    def run(
        cls,
        project: LeanProject,
        stream_logs: bool = False,
        timeout: int = 600,
    ) -> LeanRun:
        """Docker로 Lean 백테스트 실행
        
        Args:
            project: Lean 프로젝트
            stream_logs: 로그 스트리밍 여부
            timeout: 타임아웃 (초)
        
        Returns:
            LeanRun 결과 객체
        
        Raises:
            RuntimeError: 실행 실패 시
        """
        started_at = datetime.now()
        output_dir = project.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 경로 (절대 경로로 변환)
        workspace = project.project_dir.parent.parent.resolve()
        project_path = project.project_dir.resolve()
        data_path = (workspace / "data").resolve()
        results_path = output_dir.resolve()
        
        # 디버깅: 경로 확인
        logger.info(f"[Lean] workspace: {workspace}")
        logger.info(f"[Lean] project_path: {project_path}")
        logger.info(f"[Lean] data_path: {data_path}")
        logger.info(f"[Lean] results_path: {results_path}")
        
        # 데이터 폴더 존재 확인
        if not data_path.exists():
            raise RuntimeError(f"데이터 폴더가 없습니다: {data_path}")
        
        symbol_props = data_path / "symbol-properties" / "symbol-properties-database.csv"
        if not symbol_props.exists():
            raise RuntimeError(f"symbol-properties-database.csv가 없습니다. setup_lean_data.sh 실행 필요: {symbol_props}")
        
        # Lean config.json 생성
        lean_config = {
            "algorithm-type-name": "Algorithm",
            "algorithm-language": "Python",
            "debugging": False,
            "debugging-method": "LocalCmdLine",
            "log-handler": "ConsoleLogHandler",
            "messaging-handler": "QuantConnect.Messaging.Messaging",
            "job-queue-handler": "QuantConnect.Queues.JobQueue",
            "api-handler": "QuantConnect.Api.Api",
            "map-file-provider": "QuantConnect.Data.Auxiliary.LocalDiskMapFileProvider",
            "factor-file-provider": "QuantConnect.Data.Auxiliary.LocalDiskFactorFileProvider",
            "data-provider": "QuantConnect.Lean.Engine.DataFeeds.DefaultDataProvider",
            "object-store": "QuantConnect.Lean.Engine.Storage.LocalObjectStore",
            "data-aggregator": "QuantConnect.Lean.Engine.DataFeeds.AggregationManager",
            "environments": {
                "backtesting": {
                    "live-mode": False,
                    "setup-handler": "QuantConnect.Lean.Engine.Setup.BacktestingSetupHandler",
                    "result-handler": "QuantConnect.Lean.Engine.Results.BacktestingResultHandler",
                    "data-feed-handler": "QuantConnect.Lean.Engine.DataFeeds.FileSystemDataFeed",
                    "real-time-handler": "QuantConnect.Lean.Engine.RealTime.BacktestingRealTimeHandler",
                    "history-provider": "QuantConnect.Lean.Engine.HistoricalData.SubscriptionDataReaderHistoryProvider",
                    "transaction-handler": "QuantConnect.Lean.Engine.TransactionHandlers.BacktestingTransactionHandler"
                }
            },
            "environment": "backtesting"
        }

        config_path = project_path / "lean-config.json"

        # Docker 명령어 구성
        if LEAN_DOCKER_VOLUME_NAME:
            # DooD 모드: 네임드 볼륨을 통해 sibling 컨테이너와 데이터 공유
            rel_project = str(project_path.relative_to(LEAN_WORKSPACE_MOUNT))
            rel_results = str(results_path.relative_to(LEAN_WORKSPACE_MOUNT))
            rel_config = str(config_path.relative_to(LEAN_WORKSPACE_MOUNT))

            lean_config["algorithm-location"] = f"/Workspace/{rel_project}/main.py"
            lean_config["data-folder"] = "/Workspace/data"
            lean_config["results-destination-folder"] = f"/Workspace/{rel_results}"
            config_path.write_text(json.dumps(lean_config, indent=2))

            cmd = [
                "docker", "run", "--rm",
                "-v", f"{LEAN_DOCKER_VOLUME_NAME}:/Workspace",
                "--entrypoint", "/bin/bash",
                LEAN_IMAGE,
                "-c",
                f"cp /Workspace/{rel_config} /Lean/Launcher/bin/Debug/config.json && "
                f"dotnet /Lean/Launcher/bin/Debug/QuantConnect.Lean.Launcher.dll",
            ]
        else:
            # 로컬 모드: 바인드 마운트 사용
            lean_config["algorithm-location"] = "/Algorithm/main.py"
            lean_config["data-folder"] = "/Data"
            lean_config["results-destination-folder"] = "/Results"
            config_path.write_text(json.dumps(lean_config, indent=2))

            cmd = [
                "docker", "run", "--rm",
                "-v", f"{project_path}:/Algorithm:ro",
                "-v", f"{data_path}:/Data:ro",
                "-v", f"{results_path}:/Results",
                "-v", f"{config_path}:/Lean/Launcher/bin/Debug/config.json:ro",
                LEAN_IMAGE,
            ]
        
        logger.info(f"[Lean] Docker 실행: {project.run_id}")
        logger.debug(f"[Lean] 명령어: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            
            finished_at = datetime.now()
            duration = (finished_at - started_at).total_seconds()
            stdout = result.stdout + result.stderr
            
            if result.returncode != 0:
                error_msg = f"Lean 백테스트 실패 (exit code: {result.returncode})\n{stdout[-2000:]}"
                logger.error(f"[Lean] {error_msg}")
                raise RuntimeError(error_msg)
            
            # 성공 결과 생성
            run = LeanRun(
                project=project,
                success=True,
                output_dir=output_dir,
                duration_seconds=duration,
                started_at=started_at,
                finished_at=finished_at,
            )
            
            run.load_result()
            
            logger.info(f"[Lean] 완료: {duration:.1f}초")
            return run
            
        except subprocess.TimeoutExpired:
            error_msg = f"Lean 백테스트 타임아웃 ({timeout}초)"
            logger.error(f"[Lean] {error_msg}")
            raise RuntimeError(error_msg)
        
        except FileNotFoundError:
            error_msg = "Docker가 설치되지 않았습니다."
            logger.error(f"[Lean] {error_msg}")
            raise RuntimeError(error_msg)
    
    _pull_process: subprocess.Popen = None

    @classmethod
    def pull_image_background(cls) -> None:
        """Lean Docker 이미지 백그라운드 다운로드 시작"""
        if cls._pull_process and cls._pull_process.poll() is None:
            return  # 이미 다운로드 중

        # 이전 pull 실패 여부 로깅
        if cls._pull_process is not None:
            rc = cls._pull_process.returncode
            if rc != 0:
                logger.warning(f"[Lean] 이전 이미지 다운로드 실패 (exit code: {rc})")

        logger.info(f"[Lean] Docker 이미지 백그라운드 다운로드 시작: {LEAN_IMAGE}")
        cls._pull_process = subprocess.Popen(
            ["docker", "pull", LEAN_IMAGE],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    @classmethod
    def is_pulling(cls) -> bool:
        """이미지 다운로드 진행 중 여부"""
        return cls._pull_process is not None and cls._pull_process.poll() is None

    @classmethod
    def wait_for_pull(cls, timeout: int = 600) -> bool:
        """백그라운드 pull 완료 대기. 성공 여부 반환."""
        if cls._pull_process is None:
            return False
        if cls._pull_process.poll() is not None:
            return cls._pull_process.returncode == 0
        try:
            _, stderr = cls._pull_process.communicate(timeout=timeout)
            rc = cls._pull_process.returncode
            if rc != 0:
                logger.error(f"[Lean] 이미지 다운로드 실패 (exit code: {rc}): {stderr.decode(errors='replace')[-500:]}")
            else:
                logger.info(f"[Lean] 이미지 다운로드 완료: {LEAN_IMAGE}")
            return rc == 0
        except subprocess.TimeoutExpired:
            logger.error(f"[Lean] 이미지 다운로드 타임아웃 ({timeout}초)")
            cls._pull_process.kill()
            return False

    @classmethod
    def pull_image(cls) -> bool:
        """Lean Docker 이미지 다운로드 (동기)"""
        try:
            logger.info(f"[Lean] Docker 이미지 다운로드 중: {LEAN_IMAGE}")
            result = subprocess.run(
                ["docker", "pull", LEAN_IMAGE],
                capture_output=True,
                text=True,
                timeout=1800,
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"[Lean] 이미지 다운로드 실패: {e}")
            return False
    
    @classmethod
    def check_docker(cls) -> bool:
        """Docker 실행 확인"""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        
        return False
    
    @classmethod
    def check_image(cls) -> bool:
        """Lean 이미지 존재 확인"""
        try:
            result = subprocess.run(
                ["docker", "images", "-q", LEAN_IMAGE],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return bool(result.stdout.strip())
        except Exception:
            return False
