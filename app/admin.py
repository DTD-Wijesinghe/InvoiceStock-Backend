"""Platform administration is isolated from business-owner permissions."""
from datetime import timedelta
from typing import Annotated, Literal
from fastapi import Depends, HTTPException
from pydantic import Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .db import User, Business, Subscription, BillingOrder, Feedback, BackupRecord, AccountState, AuthSession, Audit, now
from .schemas import Input
from .saas import access_status, subscription, utc
from .services import serialize, audit, tenant_lock

APP_INFO={'name':'InvoiceStock AI','version':'0.2.0','release_date':'2026-09-08','developer':'D.T.D.Wijesinghe','contact':'danidu.wijesinghe@outlook.com',
          'description':'Business invoicing, stock control, payment reporting and approval-based assistants.','license':'Developed for D.T.D.Wijesinghe.'}


class AccountAction(Input):
    disabled: bool
    reason: str = Field(min_length=5,max_length=300)


class SubscriptionAction(Input):
    action: Literal['suspend','unsuspend','extend']
    days: int = Field(default=0, ge=0, le=90)
    reason: str = Field(min_length=5,max_length=300)


class FeedbackAction(Input):
    status: Literal['received','reviewing','resolved']


def install_admin_routes(app, auth, db_dependency):
    Actor=Annotated[User,Depends(auth)]
    DB=Annotated[Session,Depends(db_dependency)]

    def require_admin(user):
        if user.role!='platform_admin':
            raise HTTPException(403,'Platform administrator access required')

    @app.get('/api/about')
    def about(user:Actor):
        return APP_INFO

    @app.get('/api/admin/overview')
    def overview(user:Actor,db:DB):
        require_admin(user)
        owners=list(db.scalars(select(User).where(User.role=='owner')))
        states=[access_status(db,o) for o in owners]
        amount=db.scalar(select(func.coalesce(func.sum(BillingOrder.amount),0)).where(BillingOrder.status=='paid'))
        return {'businesses':len(owners),'users':db.scalar(select(func.count()).select_from(User).where(User.role!='platform_admin')),
                'trial':sum(s['state']=='trial' for s in states),'active':sum(s['state']=='active' for s in states),
                'blocked':sum(s['blocked'] for s in states),'subscription_revenue':str(amount),
                'open_feedback':db.scalar(select(func.count()).select_from(Feedback).where(Feedback.status!='resolved')),'app':APP_INFO}

    @app.get('/api/admin/businesses')
    def businesses(user:Actor,db:DB):
        require_admin(user)
        rows=[]
        for owner in db.scalars(select(User).where(User.role=='owner').order_by(User.created_at.desc()).limit(500)):
            b=db.get(Business,owner.business_id)
            rows.append({'id':b.id,'name':b.name,'created_at':b.created_at.isoformat(),'owner':owner.name,'email':owner.email,'subscription':access_status(db,owner)})
        return rows

    @app.post('/api/admin/businesses/{bid}/subscription')
    def manage_subscription(bid:str,data:SubscriptionAction,user:Actor,db:DB):
        require_admin(user)
        owner=db.scalar(select(User).where(User.business_id==bid,User.role=='owner'))
        if not owner:raise HTTPException(404,'Business not found')
        tenant_lock(db,owner)
        sub=subscription(db,owner)
        before=serialize(sub)
        if data.action=='extend':
            if data.days<1:raise HTTPException(422,'Extension must be at least one day')
            sub.paid_until=max(now(),utc(sub.paid_until) or now(),utc(sub.trial_ends_at))+timedelta(days=data.days)
        else:sub.suspended=data.action=='suspend'
        db.add(Audit(business_id=bid,actor=user.id,action='admin_subscription_'+data.action,entity_id=sub.id,before=before,after={**serialize(sub),'reason':data.reason}))
        return access_status(db,owner)

    @app.get('/api/admin/users')
    def users(user:Actor,db:DB):
        require_admin(user)
        rows=[]
        for u in db.scalars(select(User).where(User.role!='platform_admin').order_by(User.created_at.desc()).limit(500)):
            state=db.scalar(select(AccountState).where(AccountState.user_id==u.id))
            rows.append({**serialize(u),'disabled':bool(state and state.disabled)})
        return rows

    @app.post('/api/admin/users/{uid}/access')
    def user_access(uid:str,data:AccountAction,user:Actor,db:DB):
        require_admin(user)
        u=db.get(User,uid)
        if not u or u.role=='platform_admin':raise HTTPException(404,'Managed user not found')
        tenant_lock(db,u)
        state=db.scalar(select(AccountState).where(AccountState.user_id==uid))
        if not state:
            state=AccountState(business_id=u.business_id,user_id=uid)
            db.add(state)
        state.disabled=data.disabled
        if data.disabled:
            for token in db.scalars(select(AuthSession).where(AuthSession.user_id==uid)):db.delete(token)
        db.add(Audit(business_id=u.business_id,actor=user.id,action='admin_user_access_changed',entity_id=uid,after={'disabled':data.disabled,'reason':data.reason}))
        return {'disabled':data.disabled}

    @app.get('/api/admin/feedback')
    def all_feedback(user:Actor,db:DB):
        require_admin(user)
        return [serialize(f) for f in db.scalars(select(Feedback).order_by(Feedback.created_at.desc()).limit(500))]

    @app.post('/api/admin/feedback/{fid}')
    def review_feedback(fid:str,data:FeedbackAction,user:Actor,db:DB):
        require_admin(user)
        f=db.get(Feedback,fid)
        if not f:raise HTTPException(404,'Feedback not found')
        f.status=data.status
        db.add(Audit(business_id=f.business_id,actor=user.id,action='admin_feedback_reviewed',entity_id=f.id,after={'status':data.status}))
        return serialize(f)

    @app.get('/api/admin/audit')
    def admin_audit(user:Actor,db:DB):
        require_admin(user)
        return [serialize(a) for a in db.scalars(select(Audit).where(Audit.action.like('admin_%')).order_by(Audit.created_at.desc()).limit(200))]

    @app.get('/api/admin/backups')
    def backup_history(user:Actor,db:DB):
        require_admin(user)
        return [serialize(b) for b in db.scalars(select(BackupRecord).order_by(BackupRecord.created_at.desc()).limit(200))]
