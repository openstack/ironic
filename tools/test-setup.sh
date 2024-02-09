#!/bin/bash -xe

# This script will be run by OpenStack CI before unit tests are run,
# it sets up the test system as needed.
# Developers should setup their test systems in a similar way.

# Try starting mariadb
sudo systemctl start mariadb || true
# Try starting postgresql
sudo postgresql-setup --initdb || true
sudo systemctl start postgresql || true

# This setup needs to be run as a user that can run sudo.

# The root password for the MySQL database; pass it in via
# MYSQL_ROOT_PW.
DB_ROOT_PW=${MYSQL_ROOT_PW:-insecure_slave}

# This user and its password are used by the tests, if you change it,
# your tests might fail.
DB_USER=openstack_citest
DB_PW=openstack_citest

sudo -H mysqladmin -u root password $DB_ROOT_PW

# It's best practice to remove anonymous users from the database.  If
# a anonymous user exists, then it matches first for connections and
# other connections from that host will not work.
sudo -H mysql -u root -p$DB_ROOT_PW -h localhost -e "
    DELETE FROM mysql.user WHERE User='';
    FLUSH PRIVILEGES;
    CREATE USER '$DB_USER'@'%' IDENTIFIED BY '$DB_PW';
    GRANT ALL PRIVILEGES ON *.* TO '$DB_USER'@'%' WITH GRANT OPTION;"

# Now create our database.
mysql -u $DB_USER -p$DB_PW -h 127.0.0.1 -e "
    SET default_storage_engine=MYISAM;
    DROP DATABASE IF EXISTS openstack_citest;
    CREATE DATABASE openstack_citest CHARACTER SET utf8;"

# Same for PostgreSQL
# The root password for the PostgreSQL database; pass it in via
# POSTGRES_ROOT_PW.
DB_ROOT_PW=${POSTGRES_ROOT_PW:-insecure_slave}

# Change working directory to a folder all users can access
# as psql on centos8 needs to be able to open the working directory
# which it can't when executed as the postgres user, which is required
# as same user as process for initial administrative authentication to
# the postgres database
cd /tmp

# Identify and update the postgres hba file which can be in
# a version specific path.
PG_HBA=$(sudo -H -u postgres psql -t -c "show hba_file")
PG_CONF=$(sudo -H -u postgres psql -t -c "show config_file")

# setup postgres encryption algorithm and authentication
sudo sed -i 's/ident$/scram-sha-256/g' $PG_HBA
sudo sed -i 's/md5$/scram-sha-256/g' $PG_HBA
sudo sed -i 's/^.*password_encryption =.*/password_encryption = scram-sha-256/' $PG_CONF

sudo cat $PG_HBA
sudo cat $PG_CONF

# restart postgres with new HBA file is loaded
sudo systemctl stop postgresql || true
sudo systemctl start postgresql || true

# Setup user
root_roles=$(sudo -H -u postgres psql -t -c "
    SELECT 'HERE' from pg_roles where rolname='$DB_USER'")
if [[ ${root_roles} == *HERE ]];then
    sudo -H -u postgres psql -c "ALTER ROLE $DB_USER WITH SUPERUSER LOGIN PASSWORD '$DB_PW'"
else
    sudo -H -u postgres psql -c "CREATE ROLE $DB_USER WITH SUPERUSER LOGIN PASSWORD '$DB_PW'"
fi

# Store password for tests
cat << EOF > $HOME/.pgpass
*:*:*:$DB_USER:$DB_PW
EOF
chmod 0600 $HOME/.pgpass

# Now create our database
psql -h 127.0.0.1 -U $DB_USER -d postgres -c "DROP DATABASE IF EXISTS openstack_citest"
createdb -h 127.0.0.1 -U $DB_USER -l C -T template0 -E utf8 openstack_citest
