"""Gateway runner — claims validate+preview jobs, safe-extracts, runs the validator and engine
preview, writes done-files. Runs inside the engine image with network_mode none (design §1/§5).
Never touches the gateway DB (house rule).
"""
