"""Artifact transport on the node (P4.3): job inputs from the master, job results to it.

artifact_client.py  HTTPS to the master's artifact routes with the node credential and the pinned CA
artifact_cache.py   a bounded, hash-checked cache in the node's state volume
node_artifacts.py   load and store as the job runner calls them (cluster/node/jobs/job_runner.py)
"""
