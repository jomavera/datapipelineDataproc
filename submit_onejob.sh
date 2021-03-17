#!/bin/bash
gcloud dataproc jobs submit pyspark \
       --cluster sparktodp \
       --region us-central1 \
       transform.py \
       -- --bucket=$1