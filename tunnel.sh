#!/bin/bash

sudo socat TCP-LISTEN:11434,bind=0.0.0.0,fork TCP:192.168.178.144:11434