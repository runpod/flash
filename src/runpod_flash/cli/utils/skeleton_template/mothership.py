"""
Mothership Endpoint Configuration

The mothership endpoint serves your FastAPI application routes.
It is automatically deployed as a CPU-optimized load-balanced endpoint.

To customize this configuration:
- Modify worker scaling: change workersMin and workersMax values
- Use GPU load balancer: import LiveLoadBalancer instead of CpuLiveLoadBalancer
- Change endpoint name: update the 'name' parameter

To disable mothership deployment:
- Delete this file, or
- Comment out the 'mothership' variable below

Documentation: https://docs.runpod.io/flash/mothership
"""

from runpod_flash import CpuLiveLoadBalancer

# Mothership endpoint configuration
# This serves your FastAPI app routes from main.py
mothership = CpuLiveLoadBalancer(
    name="mothership",
    workersMin=1,
    workersMax=1,
)

# Examples of customization:

# Increase scaling for high traffic
# mothership = CpuLiveLoadBalancer(
#     name="mothership",
#     workersMin=2,
#     workersMax=10,
# )

# Use GPU-based load balancer instead of CPU
# (requires importing LiveLoadBalancer)
# from runpod_flash import LiveLoadBalancer
# mothership = LiveLoadBalancer(
#     name="mothership",
#     gpus=[GpuGroup.ANY],
# )

# Custom endpoint name
# mothership = CpuLiveLoadBalancer(
#     name="my-api-gateway",
#     workersMin=1,
#     workersMax=1,
# )

# To disable mothership:
# - Delete this entire file, or
# - Comment out the 'mothership' variable above
