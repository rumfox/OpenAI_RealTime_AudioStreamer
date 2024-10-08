import asyncio
import base64
import json
import os
import pyaudio
import shutil
import websockets
from dotenv import load_dotenv
import threading

# .env 파일 로드
load_dotenv("openai.env")


class AudioStreamer:

	# 초기화 : AudioStreamer 클래스가 초기화
	# PyAudio 객체(self.p)와 비동기 큐(self.audio_queue) 생성
	# 큐는 마이크 입력을 스레드 간 안전하게 전달하는 데 사용
    def __init__(self):
        self.p = pyaudio.PyAudio()
        self.audio_queue = asyncio.Queue() 

    # 마이크 오디오 입력 콜백 : 마이크에서 입력된 오디오 데이터 base64로 인코딩
    # --> 큐 추가 비동기 작업 이벤트 루프에 예약 
    # asyncio.run_coroutine_threadsafe() 사용해 현재 루프(self.loop)에 작업 추가 
    # --> PyAudio 콜백 별도의 스레드에서 호출되기 때문에 사용
    def mic_audio_in_callback(self, in_data, frame_count, time_info, status):
        payload = base64.b64encode(in_data).decode("utf-8")
        asyncio.run_coroutine_threadsafe(self.audio_queue.put(payload), self.loop)
        return (None, pyaudio.paContinue)

	# 웹소켓 수신 워커 : WebSocket을 통해 받은 메시지 처리 비동기 함수
	# 메시지가 수신될 때마다 터미널에 메시지를 출력
	# session.created 메시지를 수신하면 마이크 스트리밍 시작
	# response.audio.delta 메시지 수신하면 오디오 데이터를 디코딩하여 스피커로 출력 
    async def ws_receive_worker(self):
        async for m in self.ws:
            columns, rows = shutil.get_terminal_size()
            maxl = columns - 5
            print(m if len(m) <= maxl else (m[:maxl] + " ..."))
            evt = json.loads(m)
            if evt["type"] == "session.created":
                print("Connected: say something to GPT-4o")
                self.mic_audio_in.start_stream()
            elif evt["type"] == "response.audio.delta":
                audio = base64.b64decode(evt["delta"])
                self.speaker_audio_out.write(audio)

    # 오디오 전송 워커 : 큐에서 오디오 데이터를 가져와 WebSocket으로 전송하는 비동기 함수
    # audio_queue.get()으로 큐에서 데이터를 가져와 OpenAI API로 전달 
    # 비동기적으로 실행되며, 큐에 데이터가 있을 때마다 WebSocket에 전송 
    async def send_audio_worker(self):
        # 큐에서 오디오 데이터를 가져와 WebSocket으로 전송
        while True:
            payload = await self.audio_queue.get()
            await self.ws.send(
                json.dumps(
                    {
                        "type": "input_audio_buffer.append",
                        "audio": payload,
                    },
                )
            )

    # 메인 실행 (run 메서드) : 
    # PyAudio 사용 마이크 스트림(self.mic_audio_in)과 스피커 스트림(self.speaker_audio_out) 설정 
    # 설정 후 OpenAI WebSocket 서버에 연결하여 세션 시작
    # WebSocket 수신 워커와 오디오 전송 워커 비동기 실행 
    # 마지막으로 await asyncio.sleep(15 * 60)을 호출해 프로그램을 15분 동안 유지
    async def run(self):
        self.loop = asyncio.get_running_loop()

        self.mic_audio_in = self.p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=24000,
            input=True,
            stream_callback=self.mic_audio_in_callback,
            frames_per_buffer=int(24000 / 100) * 2,  # 20ms of audio
            start=False,
        )

        self.speaker_audio_out = self.p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=24000,
            output=True,
        )

        self.ws = await websockets.connect(
            uri="wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01",
            extra_headers={
                "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
                "OpenAI-Beta": "realtime=v1",
            },
        )

        # WebSocket 수신 및 오디오 전송 작업 시작
        asyncio.create_task(self.ws_receive_worker())
        asyncio.create_task(self.send_audio_worker())

        await asyncio.sleep(15 * 60)

# 이벤트 루프 설정 : 프로그램이 시작될 때 새로운 이벤트 루프 생성하고 설정
# 이 이벤트 루프에서 AudioStreamer 객체의 run 메서드 실행 
# 여기서는 asyncio.new_event_loop()와 asyncio.set_event_loop() 사용 루프 생성과 설정
# loop.run_until_complete()를 통해 해당 루프에서 run() 메서드 실행
if __name__ == "__main__":
    # 새로운 이벤트 루프 생성 및 설정
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    streamer = AudioStreamer()
    loop.run_until_complete(streamer.run())

