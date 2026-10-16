# Shivers 1 한국어화 프로젝트

Windows용 어드벤처 게임 **Shivers 영어판 1.02**의 한국어화 조사 작업 공간이다.

원본 ISO/IMG는 `original/`에 읽기 전용 기준 자료로 보존한다. 추출물, 분석 자료, 실험 빌드, 런타임 증거는 각각 `extracted/`, `workspace/`, `build/`, `qa/`로 분리한다.

2026-09-05 최신 통합본: `build/shivers_ko_full_023_20260905/play.cmd`. `continue.cmd`로 기존 최신 세이브(1번 슬롯)에서 바로 이어할 수 있으며 실제 로드를 확인했다. 세이브는 `work/scummvm_saves/full`에 공유하고 별도 백업했다. 새 저널 6장과 주소록 7페이지를 포함하여 PIC 142개, VIEW 69개 자원(91프레임), 영상 자막 117개, 독립 음성 자막 86개를 반영했다. 영상 자막은 크기 13/상향 배치를 유지한다. 재현 명령과 검증 범위는 `docs/HANDOFF_2026-08-30.md` 맨 위를 참고한다. 전체 게임 수동 검수는 미완료다.

## 현재 확인된 기준

- 게임: Shivers 영어 Windows판 1.02
- SCI 인터프리터: 2.100.002
- 엔진 세대: SCI 2.1 middle
- 원본 ISO SHA-256: `62E7E35D288D7C4ACB3A04CDE1CC9865D3B24E8EB40F8CB32D86DC00B28A80C9`
- 원본 IMG SHA-256: `25ED9B107166048655D9ED20DB012A1DB06205F6F20BE42C255A93736BEAAC1C`
- ScummVM: `H:\scummvm\scummvm.exe`, 2026.3.0
- SCI 자원: 7,748개
- 추출한 script/heap/vocab/font/message: 4,800개
- heap 문자열: 11,496개
- 원본 SCI 폰트: 10개, 모두 128 엔트리

## 폴더 구성

```text
Shivers1/
├─ original/             # 변경 금지 원본 ISO/IMG
├─ extracted/            # ISO/IMG 및 SCI 자원 추출물
├─ workspace/
│  ├─ analysis/          # 조사 보고서와 CSV
│  ├─ config/            # 재현 설정
│  ├─ scripts/           # 분석·빌드·실행 도구
│  ├─ translation/       # 번역 SSOT
│  ├─ fonts/             # 폰트 실험 원본
│  ├─ graphics/          # 그래픽 번역 작업
│  └─ audio/             # 독립 음성 WAV 추출본과 매니페스트
├─ work/                 # 캐시와 PoC 전용 실행기
├─ build/                # 원본 보존형 실험 빌드
├─ dist/                 # 향후 배포 패치
├─ docs/                 # 소스 명세와 인계 문서
├─ qa/                   # 런타임 로그와 스크린샷
├─ tools/                # 프로젝트 고정 외부 도구
└─ backups/              # 교체 전 작업 산출물 백업
```

## 주요 재현 명령

```powershell
python -B workspace\scripts\inventory_shivers.py
python -B workspace\scripts\extract_sci21_resources.py
python -B workspace\scripts\extract_heap_strings.py
python -B workspace\scripts\analyze_sci_fonts.py
python -B workspace\scripts\extract_narration_audio.py
python -B workspace\scripts\build_scummvm_korean_poc.py
python -B workspace\scripts\build_scummvm_shivers_ko_runner.py
```

## 현재 PoC 판정

- ScummVM 2026.3.0의 Shivers 탐지 레코드 언어 바이트만 바꾼 별도 실행기는 `Shivers (Windows/Korean)` 탐지에 성공했다.
- `heap 930`, `heap 922`, `font 37`, `font 7` 패치 파일은 런타임에서 로드되는 것을 확인했다.
- 가장 이른 입력 화면은 `New Game → Museum Guests 이름 입력`이다.
- `font 7`이 이 화면의 `A` 출력에 관여하는 것은 확인했지만, 교체한 `가` 비트맵은 보이지 않았다. 현재 한국어 시각 출력 판정은 **FAIL**이다.
- 별도 베이크드 그래픽 경로에서는 `pic 922`의 `MUSEUM GUESTS`를 `박물관 손님`으로 바꾼 `922.p56`이 ScummVM에서 로드되고 실제 이름 입력 화면에 표시됐다. 영문 `A` 입력도 정상이며 이 단일 picture PoC는 **PASS**다.
- 현재 수정본 18개(`pic 00005`–`03113`)를 `012` 배치 PoC에 포함했다. 18개 패치 모두 정적 readback과 ScummVM 로드가 **PASS**이며, 이번 실행에서는 `pic 01020` 번역 간판이 실제 게임 화면에 표시됐다.
- `012` 입력은 수정된 `cel_000.png` 16개와 별도 `_ko.png` 2개다. 원본 `.p56`은 보존하며, 입력 해시와 원본 셀 크기·팔레트 제약은 `translated_pic_batch_03113.json`에 고정했다.
- 18개 전체의 실제 화면·상호작용 QA는 아직 끝나지 않았다. 접촉 시트와 패치 로드는 각 picture가 실제 소비됐다는 증거가 아니므로 화면별 확인이 필요하다.
- `RESOURCE.SFX`의 3만 번대 음성 계열 87개를 22.05 kHz mono 16-bit PCM WAV로 추출했다. 번역 CSV는 무자막 정적 대상 50개, 카세트 합본·분할 8개, 청취 검토 20개, 음악 가능성 기본 제외 9개로 구분한다.
- 독립 음성 작업 SSOT는 `workspace/translation/shivers_1_audio_narration_ko.csv`, WAV와 기술 매니페스트는 `workspace/audio/narration_source_en`에 있다.
- 자세한 근거는 `workspace/analysis/POC_VIS_2026-08-30.md`와 `docs/HANDOFF_2026-08-30.md`에 있다.

원본 `SIERRAW.EXE` 호환성과 전체 게임 QA는 아직 검증하지 않았다.
