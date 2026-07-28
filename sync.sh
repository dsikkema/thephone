#!/usr/bin/env bash
rsync -anv --delete --exclude-from=.gitignore . dale@cyberology:phone

echo ok
echo -n "Proceed? (y/n) "
read -n 1 proceed
echo

if [[ $proceed = 'y' ]]; then
  echo 'Sending'
  rsync -av --delete --exclude-from=.gitignore . dale@cyberology:phone
else
  echo 'Aborting'
fi
