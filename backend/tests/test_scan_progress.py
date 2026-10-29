"""扫描进度回归测试：模拟 WS 消费链路，验证 progress 消息实时产出。

背景：R9 分批物化改造后，用户反馈"没有扫描进度了"。本测试 mock 探测层，
驱动 scan_prefix 生成器，断言 progress/result 消息按预期产出且进度单调递增。
"""
import asyncio
import pytest

from src.services import scanner


@pytest.mark.asyncio
async def test_scan_prefix_streams_progress(monkeypatch):
    """scan_prefix 应产出 progress + result + done，且进度单调递增"""
    calls = {"n": 0}

    async def fake_probe(ip, tcp_ports=None, timeout=3.0):
        calls["n"] += 1
        # 模拟真实探测耗时，让批内任务错峰完成
        await asyncio.sleep(0.001)
        return {
            "ip": ip,
            "is_online": calls["n"] % 3 == 0,
            "method": "tcp" if calls["n"] % 3 == 0 else "none",
            "open_ports": [22] if calls["n"] % 3 == 0 else [],
            "mac_address": None,
            "hostname": None,
            "duration_ms": 1,
        }

    monkeypatch.setattr(scanner, "probe_single_ip", fake_probe)

    network = "10.99.0.0/27"  # 30 个主机位，小于一个批次
    progress_msgs = []
    result_msgs = []
    done_msg = None

    async for msg in scanner.scan_prefix(network, []):
        if msg["type"] == "progress":
            progress_msgs.append(msg)
        elif msg["type"] == "result":
            result_msgs.append(msg)
        elif msg["type"] == "done":
            done_msg = msg

    assert done_msg is not None, "扫描结束应产出 done 消息"
    assert done_msg["total"] == 30
    assert len(result_msgs) == 30, "每个 IP 应产出一条 result 消息"
    assert len(progress_msgs) == 30, "每个 IP 应产出一条 progress 消息"
    # 进度单调递增
    percents = [p["percent"] for p in progress_msgs]
    assert percents == sorted(percents)
    assert percents[-1] == 100.0


@pytest.mark.asyncio
async def test_scan_prefix_batch_boundaries(monkeypatch):
    """跨批次（>512 IP）时进度应持续推进且最终完成"""
    async def fake_probe(ip, tcp_ports=None, timeout=3.0):
        await asyncio.sleep(0)
        return {
            "ip": ip, "is_online": False, "method": "none",
            "open_ports": [], "mac_address": None, "hostname": None,
            "duration_ms": 0,
        }

    monkeypatch.setattr(scanner, "probe_single_ip", fake_probe)

    network = "10.98.0.0/22"  # 1022 个主机位，跨两个批次（512 + 510）
    scanned = 0
    last_percent = 0
    done = False
    async for msg in scanner.scan_prefix(network, [], max_concurrent=50):
        if msg["type"] == "progress":
            scanned = msg["scanned"]
            assert msg["percent"] >= last_percent
            last_percent = msg["percent"]
        elif msg["type"] == "done":
            done = True

    assert done
    assert scanned == 1022
    assert last_percent == 100.0


@pytest.mark.asyncio
async def test_scan_prefix_first_progress_arrives_quickly(monkeypatch):
    """首条 progress 应快速产出（不能等整批完成才推送）"""
    started_event = asyncio.Event()

    async def slow_probe(ip, tcp_ports=None, timeout=3.0):
        if not started_event.is_set():
            started_event.set()
        # 首个 IP 探测较慢
        await asyncio.sleep(0.05)
        return {
            "ip": ip, "is_online": False, "method": "none",
            "open_ports": [], "mac_address": None, "hostname": None,
            "duration_ms": 50,
        }

    monkeypatch.setattr(scanner, "probe_single_ip", slow_probe)

    first_progress_delay = None
    start = asyncio.get_running_loop().time()
    async for msg in scanner.scan_prefix("10.97.0.0/30", []):
        if msg["type"] == "progress":
            first_progress_delay = asyncio.get_running_loop().time() - start
            break
        if started_event.is_set() and first_progress_delay is None:
            continue

    assert first_progress_delay is not None, "应能收到首条 progress"
    assert first_progress_delay < 5, f"首条 progress 耗时 {first_progress_delay:.2f}s，疑似被阻塞"
