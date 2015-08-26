#!/bin/bash
host=$1 start=$2 username=$3 key=$4 goc=$5 debug=$6 timeout=$7 summary=$8 allowedEvents=$9 cert=${10} certkey=${11} directoryqueue=${12}
source ./esmond.env $host
python esmonduploader/caller.py -d $debug -s $start -u "http://"$host -p -w $username -k $key -g $goc -t $timeout -x $summary -a $allowedEvents -c $cert -o $certkey --queue $directoryqueue


