"""
Simulated OPC UA PLC server for local test-pipeline development.

Exposes a handful of process variables typical of a low-voltage switchgear /
protection panel commissioning bay (coil voltage, current draw, cycle time,
temperature, pressure, contactor + fault state) and replays a scripted
"contactor energise under inrush load" scenario: coil control voltage sags
below its 20V spec for ~2 seconds while the 80A inrush current is drawn.

This exists so the rest of the pipeline (client, deviation checks, test
report generator) can be run and demoed without needing physical hardware.
Point opc_ua_client.py at a real PLC's endpoint instead and nothing else
in the pipeline has to change.
"""

import asyncio
import math
import random
import time

from asyncua import Server, ua

ENDPOINT = "opc.tcp://127.0.0.1:4855/plc/"
NAMESPACE = "http://panel-demo.local/plc"


async def main():
    server = Server()
    await server.init()
    server.set_endpoint(ENDPOINT)
    server.set_server_name("Simulated Protection Panel PLC")

    idx = await server.register_namespace(NAMESPACE)

    objects = server.nodes.objects
    panel = await objects.add_object(idx, "ProtectionPanel")

    coil_voltage = await panel.add_variable(idx, "CoilVoltage_V", 24.0)
    current_draw = await panel.add_variable(idx, "CurrentDraw_A", 0.0)
    cycle_time = await panel.add_variable(idx, "CycleTime_ms", 0.0)
    temperature = await panel.add_variable(idx, "Temperature_C", 22.0)
    pressure = await panel.add_variable(idx, "Pressure_mbar", 1013.0)
    contactor_state = await panel.add_variable(idx, "ContactorState", "OPEN")
    fault_flag = await panel.add_variable(idx, "FaultFlag", False)

    for node in (coil_voltage, current_draw, cycle_time, temperature, pressure, contactor_state, fault_flag):
        await node.set_writable()

    print(f"Simulated PLC server running at {ENDPOINT}")
    print("Scenario: contactor energise at t=5s, inrush + coil voltage sag for ~2s")

    async with server:
        t0 = time.monotonic()
        tick = 0
        while True:
            t = time.monotonic() - t0
            tick += 1

            # baseline noise on idle channels
            await temperature.write_value(22.0 + random.uniform(-0.3, 0.3))
            await pressure.write_value(1013.0 + random.uniform(-1.5, 1.5))
            await cycle_time.write_value(round(random.uniform(8.0, 12.0), 2))

            if t < 5.0:
                await contactor_state.write_value("OPEN")
                await coil_voltage.write_value(round(24.0 + random.uniform(-0.1, 0.1), 2))
                await current_draw.write_value(0.0)
                await fault_flag.write_value(False)
            elif t < 7.0:
                # energising: inrush current spikes, coil control voltage sags.
                # Undersized control transformer means coil drops to ~18V under
                # an 80A inrush against the 20V spec floor -> TC-001 should fail.
                await contactor_state.write_value("CLOSING")
                inrush_progress = (t - 5.0) / 2.0
                sag = 6.0 * math.sin(math.pi * inrush_progress)  # dips mid-transient, min ~18V
                await coil_voltage.write_value(round(24.0 - sag, 2))
                await current_draw.write_value(round(80.0 * math.sin(math.pi * inrush_progress) + random.uniform(-1, 1), 2))
                await fault_flag.write_value(sag > 4.0)
            else:
                await contactor_state.write_value("CLOSED")
                await coil_voltage.write_value(round(24.0 + random.uniform(-0.1, 0.1), 2))
                await current_draw.write_value(round(4.5 + random.uniform(-0.2, 0.2), 2))
                await fault_flag.write_value(False)

            if t > 12.0:
                t0 = time.monotonic()  # loop the scenario

            await asyncio.sleep(1.0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped.")
