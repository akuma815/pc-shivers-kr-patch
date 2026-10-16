# Shivers 1 독립 음성 원본

`RESOURCE.SFX`의 3만 번대 전역 오디오 자원 87개를 번역 검토용 PCM WAV로 변환한 폴더다.

- `wav/audio_XXXXX.wav`: 22.05 kHz, 모노, 16-bit PCM 검토본
- `manifest.csv`: 원본 오프셋·크기·형식·길이·SHA-256과 정적 분류
- `workspace/translation/shivers_1_audio_narration_ko.csv`: 번역·한국어 녹음 작업용 SSOT

3만 번대가 음성 계열이라는 것은 스크립트의 `gSounds play` 호출과 `sNarrative` 흐름으로 확인했다. 다만 `33510~33518`은 3×3 선택식 재생기에서 쓰이며 음악일 가능성이 높아 기본 번역 대상에서 제외했고, 짧은 장면 음성 일부는 효과음 가능성이 있어 `review`로 표시했다. `306xx` 카세트 음성은 자막 끄기용 합본과 자막 켜기용 분할본이 모두 존재한다.

재생성:

```powershell
python -B workspace\scripts\extract_narration_audio.py
```

재실행 시 번역 CSV의 `english_transcript`, `korean_translation`, `korean_wav`, `status`, `notes` 열은 보존된다.
