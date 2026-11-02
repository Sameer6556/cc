# Task 5: Subnet plan for 10.20.0.0/16

## Method

1. Sort the requirements from largest to smallest: app (1,000), public (250), data (100), management (20).
2. For each subnet choose the smallest prefix whose usable hosts, `2^(32 - prefix) - 2`, cover the requirement.
3. Start at `10.20.0.0` and place each subnet immediately after the previous one. Because the blocks are
   allocated largest first and each size is a power of two, every block starts on a boundary of its own size,
   so no address is skipped.

## Working

| Subnet | Hosts needed | Too small | Chosen prefix | Usable hosts |
|---|---:|---|---|---:|
| app | 1,000 | /23 gives 2^9 - 2 = 510 | /22 | 2^10 - 2 = **1,022** |
| public | 250 | /25 gives 2^7 - 2 = 126 | /24 | 2^8 - 2 = **254** |
| data | 100 | /26 gives 2^6 - 2 = 62 | /25 | 2^7 - 2 = **126** |
| management | 20 | /28 gives 2^4 - 2 = 14 | /27 | 2^5 - 2 = **30** |

Placement (block size in addresses = 2^(32 - prefix)):

- app: starts at 10.20.0.0, size 1,024, ends at 10.20.3.255 (0.0 + 1,023 = 3.255).
- public: starts at the next address 10.20.4.0, size 256, ends at 10.20.4.255.
- data: starts at 10.20.5.0, size 128, ends at 10.20.5.127.
- management: starts at 10.20.5.128, size 32, ends at 10.20.5.159.
- The rest of the /16, 10.20.5.160 to 10.20.255.255, stays free for growth.

## Result

| Subnet | Network address | Prefix | Usable host range | Broadcast address | Usable hosts |
|---|---|---|---|---|---:|
| app | 10.20.0.0 | /22 | 10.20.0.1 to 10.20.3.254 | 10.20.3.255 | 1,022 |
| public | 10.20.4.0 | /24 | 10.20.4.1 to 10.20.4.254 | 10.20.4.255 | 254 |
| data | 10.20.5.0 | /25 | 10.20.5.1 to 10.20.5.126 | 10.20.5.127 | 126 |
| management | 10.20.5.128 | /27 | 10.20.5.129 to 10.20.5.158 | 10.20.5.159 | 30 |

The table was cross-checked with Python's `ipaddress` module (see `tests/test_network.py`).

## NACL for the public subnet

`network/nacl.json` implements the rules for the public subnet (where the load balancer lives):

| Direction | Rule | Protocol / ports | CIDR | Action | Why |
|---|---|---|---|---|---|
| inbound | 50 | all | 198.51.100.0/24 | deny | abusive range, lowest number so it is checked before the allows |
| inbound | 100 | tcp 80 | 0.0.0.0/0 | allow | HTTP |
| inbound | 110 | tcp 443 | 0.0.0.0/0 | allow | HTTPS |
| inbound | 120 | tcp 22 | 10.20.5.128/27 | allow | SSH only from management |
| inbound | 130 | tcp 1024-65535 | 10.20.0.0/22 | allow | replies from the app subnet to the load balancer's ephemeral ports |
| inbound | 32766 | all | 0.0.0.0/0 | deny | nothing else |
| outbound | 100 | tcp 8000 | 10.20.0.0/22 | allow | load balancer to the inference service |
| outbound | 110 | tcp 1024-65535 | 0.0.0.0/0 | allow | replies to clients on their ephemeral ports |
| outbound | 32766 | all | 0.0.0.0/0 | deny | nothing else |

Check: `python tools/nacl_sim.py network/nacl.json network/packets_sample.jsonl --check` gives 6 / 6
(`results/network/nacl_check.txt`, together with 16 extra edge-case packets in `network/packets_extra.jsonl`).

### Why reply rules and rule order matter

A NACL is **stateless**: it does not remember that a connection was opened, so every packet, including a
reply, is judged on its own. When a client connects to the load balancer on port 443, the answer leaves
the public subnet towards the client's ephemeral port (1024-65535). No outbound rule mentions port 443 on
the client side, so without outbound rule 110 every response would be dropped. The same applies to the
load balancer's own connections to the app subnet: the request goes out on TCP 8000 (outbound rule 100),
but the app's answer arrives on one of the load balancer's ephemeral ports and needs inbound rule 130.
A stateful security group would allow both replies automatically.

Rules are evaluated from the lowest number upward and the **first match wins**. Traffic from
198.51.100.0/24 to port 443 matches both the deny and the "443 from anywhere" allow, so the deny only works
if its number is lower than the allow it must override. Renumbering the deny from 50 to 140 lets packet S04
(443 from 198.51.100.9) through via rule 110 (`results/network/nacl_wrong_order_check.txt`, 5 / 6).

Limitation: because the NACL cannot tell a reply from a new connection, the outbound "1024-65535 to
anywhere" rule would also let the load balancer open new connections to any high port. Tightening that
needs stateful filtering (security groups) on the instances.
