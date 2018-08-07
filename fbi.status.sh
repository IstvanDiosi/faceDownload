echo "Total in rows in" $1
cat  $1 | wc
echo "OK in"
cat  $1 | grep OK | wc
echo "ERROR in"
cat  $1 | grep ERROR | wc
echo "EMPTY in"
cat  $1 | grep EMPTY | wc 
cat $2 | grep worker | grep -e STARTED -e STOPPED | tail -20
cat $2 | grep uploader | grep -e STARTED -e STOPPED | tail -20
cat $2 | grep qman | grep -e init -e exit | tail -10
cat $2 | grep qman | grep resultq| tail -2

