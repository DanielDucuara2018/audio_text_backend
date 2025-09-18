#!/bin/bash
set -e

declare -A databases=(
    [reporter]=audiotext
)

echo ${!databases[@]}

for user in "${!databases[@]}";
do

    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
        CREATE USER $user PASSWORD '$user';
        CREATE USER ${user}_test PASSWORD '$user';
        CREATE DATABASE ${databases["$user"]};
        CREATE DATABASE ${databases["$user"]}_test;
        GRANT ALL PRIVILEGES ON DATABASE ${databases["$user"]} TO $user;
        GRANT ALL PRIVILEGES ON DATABASE ${databases["$user"]}_test TO ${user}_test;
EOSQL

done
