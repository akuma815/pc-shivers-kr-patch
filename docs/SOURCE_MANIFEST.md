# Source Manifest

기록일: 2026-08-30

| 역할 | 프로젝트 상대 경로 | 크기 (bytes) | SHA-256 |
|---|---|---:|---|
| 원본 설치 CD 이미지 | `original/installer/SHIVCD.iso` | 424,298,496 | `62E7E35D288D7C4ACB3A04CDE1CC9865D3B24E8EB40F8CB32D86DC00B28A80C9` |
| 설치 완료 파일 이미지 | `original/installed/image.img` | 5,243,392 | `25ED9B107166048655D9ED20DB012A1DB06205F6F20BE42C255A93736BEAAC1C` |

두 파일은 프로젝트 구조 정리 전후와 초기 조사 완료 시점에 SHA-256을 다시 계산했으며 값이 동일했다.

## 확인된 형식

- `SHIVCD.iso`: ISO 9660, 볼륨 ID `SHIVCD`, Shivers 영어 Windows판 1.02 설치 CD
- `image.img`: MBR이 있는 FAT16 디스크 이미지, 활성 파티션 시작 LBA 8
- IMG에는 설치본과 함께 저장 이름 `DOOGIE`의 저장 데이터가 포함되어 있다.

이미지 자체는 기준 원본으로 읽기 전용 취급한다. 내부 파일 분석은 `extracted/` 복사본에서 수행한다.
