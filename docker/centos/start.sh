#!/bin/bash
docker run -d \
  --name centos7 \
  -v /Users/raidery/bench/centos7:/root/bench \
  quay.io/centos/centos:7.6.1810 \
  tail -f /dev/null