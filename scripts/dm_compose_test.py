import sys
import main

peer = sys.argv[1] if len(sys.argv) > 1 else ""
print(main.compose_wormhole_dm(peer_id=peer, peer_dh_pub="", plaintext="fleet-dm-probe"))
