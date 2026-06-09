#!/bin/bash
#SBATCH -J example_hpc_job
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -t 00:10:00
#SBATCH -o slurm-%j.out
#SBATCH -e slurm-%j.err

set -euo pipefail

mkdir -p results
date > results/finished_at.txt
hostname > results/ran_on.txt
echo "Replace this with your simulation or batch workload." > results/output.txt
