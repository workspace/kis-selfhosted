import logging
import os
import requests
import yaml


def setup_kis_config(force_update=False):
    """KIS 설정 파일 자동 생성 (템플릿 다운로드 + 환경변수로 값 덮어쓰기)

    Args:
        force_update (bool): True면 기존 파일이 있어도 강제로 덮어쓰기
    """

    # KIS_CONFIG_DIR 환경변수 우선, 없으면 ~/KIS/config 사용
    kis_config_dir = os.environ.get("KIS_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), "KIS", "config")

    # KIS 설정 디렉토리 생성
    os.makedirs(kis_config_dir, exist_ok=True)

    # 설정 파일 경로
    kis_config_path = os.path.join(kis_config_dir, "kis_devlp.yaml")

    # KIS_CONFIG_DIR로 외부에서 제공된 설정 파일이 있으면 그대로 사용
    if os.environ.get("KIS_CONFIG_DIR") and os.path.exists(kis_config_path):
        logging.info(f"✅ 외부 제공 KIS 설정 파일 사용: {kis_config_path}")
        return True

    # 기존 파일 존재 확인
    if os.path.exists(kis_config_path) and not force_update:
        logging.info(f"✅ KIS 설정 파일이 이미 존재합니다: {kis_config_path}")
        logging.info("기존 파일을 사용합니다. 강제 업데이트가 필요한 경우 force_update=True 옵션을 사용하세요.")
        return True

    # 1. kis_devlp.yaml 템플릿 다운로드
    template_url = "https://raw.githubusercontent.com/workspace/kis-selfhosted/refs/heads/main/kis_devlp.yaml"

    try:
        logging.info("KIS 설정 템플릿을 다운로드 중...")
        response = requests.get(template_url, timeout=30)
        response.raise_for_status()

        # 원본 템플릿 텍스트 보존
        template_content = response.text
        logging.info("✅ KIS 설정 템플릿 다운로드 완료")

    except Exception as e:
        logging.error(f"❌ KIS 설정 템플릿 다운로드 실패: {e}")
        return False

    # 2. 환경변수로 민감한 정보 덮어쓰기
    # 필수값 (누락 시 경고)
    app_key = os.getenv("KIS_APP_KEY")
    app_secret = os.getenv("KIS_APP_SECRET")

    if not app_key or not app_secret:
        logging.warning("⚠️ 필수 환경변수가 설정되지 않았습니다:")
        if not app_key:
            logging.warning("  - KIS_APP_KEY")
        if not app_secret:
            logging.warning("  - KIS_APP_SECRET")
        logging.warning("실제 거래 API 사용이 불가능할 수 있습니다.")

    # 선택적 값들 (누락 시 빈값 또는 기본값)
    paper_app_key = os.getenv("KIS_PAPER_APP_KEY", "")
    paper_app_secret = os.getenv("KIS_PAPER_APP_SECRET", "")
    hts_id = os.getenv("KIS_HTS_ID", "")
    acct_stock = os.getenv("KIS_ACCT_STOCK", "")
    acct_future = os.getenv("KIS_ACCT_FUTURE", "")
    paper_stock = os.getenv("KIS_PAPER_STOCK", "")
    paper_future = os.getenv("KIS_PAPER_FUTURE", "")
    prod_type = os.getenv("KIS_PROD_TYPE", "01")  # 기본값: 종합계좌
    url_rest = os.getenv("KIS_URL_REST", "")
    url_rest_paper = os.getenv("KIS_URL_REST_PAPER", "")
    url_ws = os.getenv("KIS_URL_WS", "")
    url_ws_paper = os.getenv("KIS_URL_WS_PAPER", "")

    # 3. YAML 파싱하여 값 업데이트
    try:
        # YAML 파싱 (주석 보존을 위해 ruamel.yaml 사용하거나, 간단히 pyyaml 사용)
        config = yaml.safe_load(template_content)

        # 환경변수 값이 있으면 해당 필드만 업데이트
        if app_key:
            config['my_app'] = app_key
            logging.info(f"✅ 실전 App Key 설정 완료")
        if app_secret:
            config['my_sec'] = app_secret
            logging.info(f"✅ 실전 App Secret 설정 완료")

        if paper_app_key:
            config['paper_app'] = paper_app_key
            logging.info(f"✅ 모의 App Key 설정 완료")
        if paper_app_secret:
            config['paper_sec'] = paper_app_secret
            logging.info(f"✅ 모의 App Secret 설정 완료")

        if hts_id:
            config['my_htsid'] = hts_id
            logging.info(f"✅ HTS ID 설정 완료: {hts_id}")
        else:
            logging.warning("⚠️ KIS_HTS_ID 환경변수가 설정되지 않았습니다.")

        if acct_stock:
            config['my_acct_stock'] = acct_stock
            logging.info(f"✅ 증권계좌 설정 완료")
        if acct_future:
            config['my_acct_future'] = acct_future
            logging.info(f"✅ 선물옵션계좌 설정 완료")
        if paper_stock:
            config['my_paper_stock'] = paper_stock
            logging.info(f"✅ 모의 증권계좌 설정 완료")
        if paper_future:
            config['my_paper_future'] = paper_future
            logging.info(f"✅ 모의 선물옵션계좌 설정 완료")

        if prod_type != "01":  # 기본값이 아닌 경우만 업데이트
            config['my_prod'] = prod_type
            logging.info(f"✅ 계좌상품코드 설정 완료: {prod_type}")

        # URL 설정 업데이트 (직접 필드)
        if url_rest:
            config['prod'] = url_rest
            logging.info(f"✅ 실전 REST URL 설정 완료")
        if url_rest_paper:
            config['vps'] = url_rest_paper
            logging.info(f"✅ 모의 REST URL 설정 완료")
        if url_ws:
            config['ops'] = url_ws
            logging.info(f"✅ 실전 WebSocket URL 설정 완료")
        if url_ws_paper:
            config['vops'] = url_ws_paper
            logging.info(f"✅ 모의 WebSocket URL 설정 완료")

        # YAML로 다시 변환
        updated_content = yaml.dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False)

    except yaml.YAMLError as e:
        logging.error(f"❌ YAML 파싱 오류: {e}")
        logging.info("문자열 치환 방식으로 대체합니다...")
        # 실패 시 기존 문자열 치환 방식 사용
        updated_content = template_content
        if app_key:
            updated_content = updated_content.replace('my_app: "앱키"', f'my_app: "{app_key}"')
        if app_secret:
            updated_content = updated_content.replace('my_sec: "앱키 시크릿"', f'my_sec: "{app_secret}"')
        if hts_id:
            updated_content = updated_content.replace('my_htsid: "사용자 HTS ID"', f'my_htsid: "{hts_id}"')
        # ... 나머지 기존 로직

    # 4. 수정된 설정을 파일로 저장 (원본 구조 보존)
    try:
        with open(kis_config_path, 'w', encoding='utf-8') as f:
            f.write(updated_content)

        logging.info(f"✅ KIS 설정 파일이 생성되었습니다: {kis_config_path}")

        # 설정 요약 출력
        logging.info("📋 KIS 설정 요약:")
        logging.info(f"  - 실제 거래: {'✅' if app_key and app_secret else '❌'}")
        logging.info(f"  - 모의 거래: {'✅' if paper_app_key and paper_app_secret else '❌'}")
        logging.info(f"  - 계좌번호: {'✅' if any([acct_stock, acct_future, paper_stock, paper_future]) else '❌'}")
        logging.info(f"  - URL 설정: {'✅' if any([url_rest, url_rest_paper, url_ws, url_ws_paper]) else '❌'}")

        return True

    except Exception as e:
        logging.error(f"❌ KIS 설정 파일 생성 실패: {e}")
        return False
