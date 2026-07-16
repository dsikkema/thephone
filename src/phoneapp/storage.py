from datetime import datetime, timezone
class Storage:
    def __init__(self, conn):
        self.conn = conn

    def get_or_create_conversation(self, participants):
        """
        Given a participants string, either get or create the ID of a conversation matching
        those participants
        """
        # cur = self.conn.execute("""
        # insert into conversations(participants) values (:participants)
        # on conflict do update set id=id returning id
        # """, {'participants': participants});


        cur = self.conn.execute(
            'select id from conversations where participants=:participants',
            {'participants': participants}
        )

        row = cur.fetchone()

        if row is None:        
            # Note: we shouldn't always do the "just in case" insert with on conflict
            # do nothing because it needlessly racks up the next autoincremented rowid
            # every time it fails to insert
            self.conn.execute("""
                insert into conversations(participants) values (:participants)
                    on conflict do nothing
                """, 
                {'participants': participants}
            );

            cur = self.conn.execute(
                'select id from conversations where participants=:participants',
                {'participants': participants}
            )

            row = cur.fetchone()

        return row[0]
    
    def save_recv_message(self, participants, sender, content, recv_at):
        """
        Lookup/create the conversation for given participants, and save the message

        (Note: for a two-person conversation, participants will be same as sender)
        """
        conv_id=self.get_or_create_conversation(participants)
        self.conn.execute("""
            insert into recv_messages(conversation_id, sender, content, recv_at)
            values
                (:conversation_id, :sender, :content, :recv_at);
            """,
            {
                'conversation_id': conv_id,
                'sender':sender,
                'content':content,
                'recv_at':int(recv_at.timestamp())
             }
        )

    def save_new_sent_message(self, participants, content, sent_at=None):
        """
        Lookup/create conversation, save message (sent_at is now)

        Return saved message ID for later marking it successfully sent
        """
        if sent_at is None:
            sent_at = datetime.now(timezone.utc)
        conv_id=self.get_or_create_conversation(participants)
        cur = self.conn.execute("""
            insert into sent_messages(conversation_id, sent_successfully, content, sent_at)
            values
                (:conversation_id, 0, :content, :sent_at)
            returning id
            """,
            {
                'conversation_id': conv_id,
                'content': content,
                'sent_at': int(sent_at.timestamp())
             }
        )

        return cur.fetchone()[0]

    def mark_successful_send(self, message_id):
        """
        Update a sent message to set its success flag true
        """
        self.conn.execute('update sent_messages set sent_successfully=1 where id=?', [message_id])

    def list_conversations(self, start=0, n=1_000_000_000_000):
        """
        List n most recent conversations starting at (start)th most recent, 
        inclusive: offset/limit paging

        Defaults to all converations

        start=0, n=5 -> most recent 5 conversations
        start=5, n=5 -> next most recent 5

        TOODO: replace with keyset pagination 

        Return a list of dictionaries keyed with:
         - converation_id
         - participants
         - preview (last message, truncated)
        """


        # TOODO: can do this with a "lateral style" subquery instead
        # of window functions?
        cur = self.conn.execute("""
            with all_messages as (
              select
                conversation_id,
                sender,
                content,
                recv_at as msg_time
              from
                recv_messages

              UNION

              select
                conversation_id,
                null as sender,
                content,
                sent_at as msg_time
              from 
                sent_messages
            )
            select
                distinct
                c.id,
                c.participants,
                substr(last_value(am.content) over (
                    partition by am.conversation_id
                    order by am.msg_time
                    range between unbounded preceding and unbounded following)
                    , 1, 30)
            from
                conversations c
                join all_messages am on am.conversation_id=c.id
            order by
                max(am.msg_time) over
                    (partition by c.id) desc
                       
            limit :n offset :start

        """,
            {
                "start": start,
                "n": n
            }
        )
        return cur.fetchall()

    def get_most_recent_conversation_content(self, conversation_id, n=5):
        """
        Get content from n most recent conversation messages

        Return list of dicts keyed by:
         - timestamp
         - sender (sender of received msg or None for a sent message)
         - content
         - sent_id (None if it is a received message)
         - recv_id (None if it is a sent message)
        """

