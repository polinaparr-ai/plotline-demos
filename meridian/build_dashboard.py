"""SQL -> DuckDB -> Python/Plotly -> a self-contained, offline-capable HTML site.
Run: .venv/bin/python build_dashboard.py
"""
from pathlib import Path
from datetime import datetime
import json,hashlib,shutil,math
import duckdb,numpy as np,pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.offline import get_plotlyjs
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression,LinearRegression
from sklearn.metrics import roc_auc_score,average_precision_score,roc_curve,precision_recall_curve,brier_score_loss
from sklearn.inspection import permutation_importance
from sklearn.ensemble import RandomForestRegressor
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score,adjusted_rand_score,r2_score,mean_absolute_error
from scipy.stats import spearmanr
from jinja2 import Environment,FileSystemLoader,select_autoescape
from prepare_data import prepare
ROOT=Path(__file__).resolve().parent
DIST=ROOT/'dist'
GREEN='#164e40';MINT='#b8d8b4';BLUE='#7598b2';GOLD='#d2a15a';INK='#20342d';SOFT='#7b8981'
COLORS={'Champions':GREEN,'Loyal':'#6b9e85','New & promising':'#9dbfc1','At risk':GOLD,'Hibernating':'#bfc4bc'}
PERIODS={
 'ytd':{'label':'Jan–Nov 2011','start':'2011-01-01','end':'2011-12-01','previous':['2010-01-01','2010-12-01']},
 'q3':{'label':'Jul–Sep 2011','start':'2011-07-01','end':'2011-10-01','previous':['2010-07-01','2010-10-01']},
 'recent':{'label':'Sep–Nov 2011','start':'2011-09-01','end':'2011-12-01','previous':['2010-09-01','2010-12-01']},
 'nov':{'label':'November 2011','start':'2011-11-01','end':'2011-12-01','previous':['2010-11-01','2010-12-01']},
 'all':{'label':'Dec 2009–Nov 2011','start':'2009-12-01','end':'2011-12-01','previous':None}}

def clean(value):
 if isinstance(value,(np.integer,)):return int(value)
 if isinstance(value,(np.floating,)):return float(value) if math.isfinite(value) else None
 if isinstance(value,(datetime,pd.Timestamp)):return value.isoformat()
 if isinstance(value,np.ndarray):return value.tolist()
 if pd.isna(value):return None
 return value

def rows(df):return json.loads(df.to_json(orient='records',date_format='iso'))
def figure(fig):return json.loads(pio.to_json(fig,remove_uids=True))
def style(fig,height=310,dark=False):
 fig.update_layout(template='none',height=height,margin=dict(l=45,r=18,t=12,b=36),paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',font=dict(family='Inter, Arial, sans-serif',size=11,color='#c3d7ca' if dark else SOFT),showlegend=False,hoverlabel=dict(bgcolor='#fff',font=dict(color=INK,size=12)),hovermode='closest',colorway=[GREEN,MINT,BLUE,GOLD],dragmode='pan')
 fig.update_xaxes(showgrid=False,zeroline=False,tickfont=dict(size=10),automargin=True)
 fig.update_yaxes(gridcolor='rgba(255,255,255,.10)' if dark else '#e9ede7',zeroline=False,tickfont=dict(size=10),automargin=True)
 return fig

def main():
 cache=prepare();DIST.mkdir(exist_ok=True)
 con=duckdb.connect(str(ROOT/'data/commerce.duckdb'))
 con.execute('CREATE OR REPLACE TABLE raw_transactions AS SELECT * FROM read_parquet(?)',[str(cache)])
 sql={p.name:p.read_text() for p in sorted((ROOT/'sql').glob('*.sql'))}
 con.execute(sql['01_ledger.sql'])
 def query(name,**params):return con.execute(sql[name],params or None).df()
 payload={'periods':PERIODS,'overview':{},'sql':sql,'source':json.loads((ROOT/'data/source.json').read_text()),'built_at':datetime.now().isoformat(timespec='seconds'),'colors':COLORS}
 print('Building SQL-backed commercial views...',flush=True)
 for key,period in PERIODS.items():
  for market in ['all','uk','international']:
   params={'start':period['start'],'end':period['end'],'market':market}
   summary=query('10_summary.sql',**params).iloc[0].to_dict()
   previous=None;prior_daily=None
   if period['previous']:
    prevparams={**params,'start':period['previous'][0],'end':period['previous'][1]}
    previous=query('10_summary.sql',**prevparams).iloc[0].to_dict()
    prior_daily=query('11_daily.sql',**prevparams)
   daily=query('11_daily.sql',**params)
   countries=query('12_countries.sql',**params)
   products=query('13_products.sql',**params)
   flow=query('22_value_flow.sql',**params)
   def weekly(df):
    if df is None or df.empty:return pd.DataFrame()
    return df.set_index(pd.to_datetime(df.day))[['net','gross','credits','orders']].resample('W-MON',label='left',closed='left').sum().reset_index()
   w=weekly(daily);wp=weekly(prior_daily)
   fig=go.Figure()
   if not wp.empty:
    fig.add_trace(go.Scatter(x=[(d+pd.DateOffset(years=1)).isoformat() for d in wp.day],y=wp.net.round(2).tolist(),mode='lines',name='Prior year',line=dict(color='#7a9d88',width=1.5,dash='dot'),hovertemplate='Prior-year week: £%{y:,.0f}<extra></extra>'))
   fig.add_trace(go.Scatter(x=[d.isoformat() for d in w.day],y=w.net.round(2).tolist(),mode='lines',name='Net sales',fill='tozeroy',fillcolor='rgba(184,216,180,.12)',line=dict(color='#c4e6bd',width=2.8,shape='spline',smoothing=.45),hovertemplate='%{x|%d %b %Y}<br>Net merchandise sales £%{y:,.0f}<extra></extra>'))
   style(fig,265,True);fig.update_layout(hovermode='x unified',margin=dict(l=45,r=12,t=12,b=30));fig.update_yaxes(tickprefix='£',tickformat='~s');fig.update_xaxes(nticks=7)
   labels=['United Kingdom','International','New customers','Existing customers','Under £150','£150–499 baskets','£500+ baskets']
   sources=[];targets=[];values=[]
   for axis1,axis2 in [('origin','lifecycle'),('lifecycle','basket')]:
    for (s,t),group in flow.groupby([axis1,axis2]):sources.append(labels.index(s));targets.append(labels.index(t));values.append(float(group.value.sum()))
   sankey=go.Figure(go.Sankey(arrangement='snap',node=dict(label=labels,pad=24,thickness=9,color=[GREEN,BLUE,'#80a185',GOLD,'#b2c9a6','#88ac92',GREEN],line=dict(width=0)),link=dict(source=sources,target=targets,value=values,color=['rgba(78,125,99,.15)' for _ in values],hovertemplate='%{source.label} → %{target.label}<br>£%{value:,.0f}<extra></extra>')))
   style(sankey,300);sankey.update_layout(margin=dict(l=3,r=3,t=22,b=10),font=dict(size=11,color=INK))
   payload['overview'][key+'_'+market]={'summary':summary,'previous':previous,'daily':rows(daily),'countries':rows(countries),'products':rows(products),'trend':figure(fig),'flow':figure(sankey),'flow_total':float(flow.value.sum())}
 print('Building customer intelligence...',flush=True)
 customers=query('20_customers.sql',cutoff='2011-12-01')
 customers['recency']=customers.recency.astype(int);payload['customers']=rows(customers)
 cohort=query('21_cohorts.sql');cohorts=sorted(cohort.cohort.unique())[-12:]
 z=[];cohort_labels=[];sizes=[]
 for co in cohorts:
  subset=cohort[cohort.cohort==co];mapping=dict(zip(subset.month_index,subset.retention));max_age=(2011-pd.Timestamp(co).year)*12+11-pd.Timestamp(co).month
  z.append([float(mapping.get(i,0)) if i<=max_age else None for i in range(12)])
  cohort_labels.append(pd.Timestamp(co).strftime('%b %Y'));sizes.append(int(subset.cohort_size.iloc[0]))
 heat=go.Figure(go.Heatmap(x=['M'+str(i) for i in range(12)],y=cohort_labels,z=z,zmin=0,zmax=1,colorscale=[[0,'#f2f4ed'],[.2,'#d1dfbd'],[.5,'#77a88b'],[1,GREEN]],xgap=5,ygap=5,showscale=False,text=[[f'{v:.0%}' if v is not None else '' for v in row] for row in z],texttemplate='%{text}',textfont=dict(size=10),hovertemplate='%{y} · %{x}<br>Active customers: %{z:.1%}<extra></extra>'))
 style(heat,380);heat.update_yaxes(autorange='reversed',showgrid=False);heat.update_xaxes(side='top');heat.update_layout(margin=dict(l=72,r=8,t=28,b=8))
 payload['cohort']={'figure':figure(heat),'sizes':sizes,'labels':cohort_labels}
 print('Training models on historical SQL features...',flush=True)
 train=query('30_model_features.sql',cutoff='2010-06-01');test=query('30_model_features.sql',cutoff='2011-06-01')
 features=['recency','frequency','monetary','average_order','units','observed_tenure','active_months']
 Xtrain=np.log1p(train[features].clip(lower=0).to_numpy());Xtest=np.log1p(test[features].clip(lower=0).to_numpy());ytrain=train.repeated.to_numpy();ytest=test.repeated.to_numpy()
 models={'forest':RandomForestClassifier(n_estimators=180,max_depth=6,min_samples_leaf=15,max_features=.8,n_jobs=2,random_state=42),'logistic':make_pipeline(StandardScaler(),LogisticRegression(max_iter=1000,random_state=42))}
 payload['models']={};modelmetrics={}
 for name,model in models.items():
  model.fit(Xtrain,ytrain);scores=model.predict_proba(Xtest)[:,1]
  fpr,tpr,_=roc_curve(ytest,scores);precision,recall,_=precision_recall_curve(ytest,scores)
  perm=permutation_importance(model,Xtest,ytest,n_repeats=4,scoring='roc_auc',random_state=42,n_jobs=2)
  importance=sorted(zip(features,perm.importances_mean),key=lambda x:x[1],reverse=True)
  metrics={'auc':roc_auc_score(ytest,scores),'ap':average_precision_score(ytest,scores),'brier':brier_score_loss(ytest,scores)}
  unseen=~test.customer_id.isin(train.customer_id).to_numpy()
  metrics['unseen_auc']=float(roc_auc_score(ytest[unseen],scores[unseen]));metrics['mean_predicted']=float(scores.mean())
  modelmetrics[name]=metrics
  payload['models'][name]={'label':'Random forest' if name=='forest' else 'Logistic regression','metrics':metrics,'scores':np.round(scores,6).tolist(),'actual':ytest.tolist(),'roc':{'x':fpr.tolist(),'y':tpr.tolist()},'pr':{'x':recall.tolist(),'y':precision.tolist()},'importance':[{'feature':k.replace('_',' ').title(),'value':float(v)} for k,v in importance]}
 payload['model_meta']={'train_cutoff':'1 Jun 2010','test_cutoff':'1 Jun 2011','test_end':'29 Aug 2011','train_n':len(train),'test_n':len(test),'prevalence':float(ytest.mean()),'features':features,'seed':42,'label':'Repeat purchase in the next 90 days','train_prevalence':float(ytrain.mean()),'unseen_n':int((~test.customer_id.isin(train.customer_id)).sum()),'baselines':sorted([{'feature':f,'auc':float(max(roc_auc_score(ytest,test[f]),1-roc_auc_score(ytest,test[f])))} for f in features],key=lambda x:-x['auc']),'note':'180-day feature window. Training snapshot is the same season one year earlier, so the repeat rate it learns matches the one it is tested on. Returning customers appear in both snapshots, so a second score covers customers the model has never seen. No IDs used as model inputs. Untuned demonstration, not a production-ready model.'}
 print('Training the spend regression...',flush=True)
 act=test.next_spend.to_numpy();pos=train.next_spend.to_numpy()>0;ylog=np.log1p(train.next_spend.to_numpy()[pos])
 reg=RandomForestRegressor(n_estimators=200,max_depth=6,min_samples_leaf=15,random_state=42,n_jobs=2).fit(Xtrain[pos],ylog)
 smear=float(np.mean(np.exp(ylog-reg.predict(Xtrain[pos]))))
 pbuy=models['forest'].predict_proba(Xtest)[:,1];cond=np.clip(np.exp(reg.predict(Xtest))*smear-1,0,None);ev=pbuy*cond
 past=test.monetary.to_numpy();tb=act>0
 base=LinearRegression().fit(np.log1p(train.monetary.to_numpy()[pos]).reshape(-1,1),ylog)
 def capture(score):k=len(act)//10;return float(act[np.argsort(-score)[:k]].sum()/act.sum())
 dec=pd.DataFrame({'p':ev,'a':act});dec['bin']=pd.qcut(dec.p.rank(method='first'),10,labels=False)
 dg=dec.groupby('bin').agg(predicted=('p','mean'),actual=('a','mean')).reset_index()
 rimp=permutation_importance(reg,Xtest[tb],np.log1p(act[tb]),n_repeats=4,scoring='r2',random_state=42,n_jobs=2)
 rng=np.random.default_rng(7);idx=np.where(tb)[0];idx=rng.choice(idx,min(900,len(idx)),replace=False)
 payload['regression']={'target':'Gross spend in the 90 days after the cutoff','train_cutoff':'1 Jun 2010','test_cutoff':'1 Jun 2011','n':int(len(act)),'buyers':int(tb.sum()),
  'mae':float(mean_absolute_error(act,ev)),'spearman':float(spearmanr(ev,act)[0]),'spearman_past':float(spearmanr(past,act)[0]),'total_pred':float(ev.sum()),'total_actual':float(act.sum()),
  'capture':capture(ev),'capture_past':capture(past),'r2_buyers':float(r2_score(np.log1p(act[tb]),reg.predict(Xtest[tb]))),'r2_buyers_past':float(r2_score(np.log1p(act[tb]),base.predict(np.log1p(past[tb]).reshape(-1,1)))),
  'deciles':rows(dg),'scatter':{'pred':np.round(cond[idx],2).tolist(),'actual':np.round(act[idx],2).tolist()},
  'importance':[{'feature':k.replace('_',' ').title(),'value':float(v)} for k,v in sorted(zip(features,rimp.importances_mean),key=lambda x:x[1],reverse=True)]}
 print('Clustering customers...',flush=True)
 cu=customers.copy();cu['tenure']=(pd.Timestamp('2011-12-01')-pd.to_datetime(cu.first_purchase)).dt.days
 CF=['recency','frequency','monetary','average_order','tenure'];Z=StandardScaler().fit_transform(np.log1p(cu[CF].clip(lower=0).astype(float)))
 ks=[]
 for k in range(2,9):
  km=KMeans(k,n_init=10,random_state=42).fit(Z);sil=float(silhouette_score(Z,km.labels_,sample_size=4000,random_state=0))
  r=np.random.default_rng(1);labs=[KMeans(k,n_init=5,random_state=int(r.integers(1e6))).fit(Z[r.integers(0,len(Z),len(Z))]).predict(Z) for _ in range(6)]
  ks.append({'k':k,'silhouette':sil,'stability':float(np.mean([adjusted_rand_score(labs[a],labs[b]) for a in range(6) for b in range(a+1,6)]))})
 best=max(ks,key=lambda x:x['silhouette'])['k'];km=KMeans(best,n_init=10,random_state=42).fit(Z);cu['cluster']=km.labels_
 prof=cu.groupby('cluster').agg(customers=('cluster','size'),recency=('recency','median'),orders=('frequency','median'),spend=('monetary','median'),average_order=('average_order','median'),tenure=('tenure','median'),total=('monetary','sum'))
 order=list(prof.sort_values('total',ascending=False).index);names={}
 names[prof.orders.idxmax()]='Regulars';rest=[c for c in order if c not in names]
 if rest:names[prof.loc[rest].recency.idxmax()]='Lapsed'
 rest=[c for c in order if c not in names]
 if len(rest)==1 and prof.loc[rest[0]].tenure<prof.tenure.median():names[rest[0]]='Newcomers'
 for i,c in enumerate([c for c in order if c not in names]):names[c]='Group '+str(i+1)
 xy=PCA(2,random_state=42).fit_transform(Z)
 payload['clusters']={'k':int(best),'by_k':ks,'features':CF,'n':int(len(cu)),'profiles':[{'name':names[c],'customers':int(prof.loc[c].customers),'share_customers':float(prof.loc[c].customers/len(cu)),'share_spend':float(prof.loc[c].total/prof.total.sum()),'recency':float(prof.loc[c].recency),'orders':float(prof.loc[c].orders),'spend':float(prof.loc[c].spend),'average_order':float(prof.loc[c].average_order),'tenure':float(prof.loc[c].tenure)} for c in order],
  'points':{'x':np.round(xy[:,0],3).tolist(),'y':np.round(xy[:,1],3).tolist(),'group':[names[c] for c in cu.cluster]},'vs_rules':float(adjusted_rand_score(cu.cluster,cu.segment))}

 print('Finding products bought together...',flush=True)
 def pairs(a,b,minsup):return query('50_affinity.sql',start=a,end=b,minsup=minsup)
 names=con.execute("SELECT stock_code,mode(description) AS d FROM ledger WHERE description IS NOT NULL GROUP BY 1").df().set_index('stock_code').d.to_dict()
 nm=lambda c:' '.join(str(names.get(c,c)).title().split())
 allp=pairs('2009-12-01','2011-12-01',40)
 top=allp[allp.lift>=5].sort_values('together',ascending=False).head(25)
 top_pairs=[{'a':nm(r.item_a),'b':nm(r.item_b),'a_code':r.item_a,'b_code':r.item_b,'together':int(r.together),'lift':float(r.lift),'share':float(r.together/min(r.baskets_a,r.baskets_b))} for r in top.itertuples()]
 long=pd.concat([allp.rename(columns={'item_a':'item','item_b':'partner','baskets_a':'item_n','baskets_b':'partner_n'})[['item','partner','together','lift','item_n','partner_n']],
  allp.rename(columns={'item_b':'item','item_a':'partner','baskets_b':'item_n','baskets_a':'partner_n'})[['item','partner','together','lift','item_n','partner_n']]])
 long['conf']=long.together/long.item_n
 biggest=long.groupby('item').item_n.first().sort_values(ascending=False).head(150).index
 picker=[]
 for it in biggest:
  g=long[(long.item==it)&(long.lift>=3)&(long.conf>=.10)].sort_values('lift',ascending=False).head(8)
  if len(g)>=3:picker.append({'code':it,'name':nm(it),'baskets':int(long[long.item==it].item_n.iloc[0]),'partners':[{'name':nm(r.partner),'together':int(r.together),'lift':float(r.lift),'conf':float(r.conf)} for r in g.itertuples()]})
 p10=pairs('2010-01-01','2011-01-01',30);p11=pairs('2011-01-01','2011-12-01',30)
 strong=p10[(p10.lift>=8)&(p10.together>=40)]
 sold11=set(con.execute("SELECT stock_code FROM ledger WHERE signed_value>0 AND invoice_date>=TIMESTAMP '2011-01-01' AND invoice_date<TIMESTAMP '2011-12-01' GROUP BY 1 HAVING count(DISTINCT invoice)>=30").df().stock_code)
 elig=strong[strong.item_a.isin(sold11)&strong.item_b.isin(sold11)]
 m11=elig.merge(p11,on=['item_a','item_b'],how='left',suffixes=('','_11'))
 kept=m11[m11.lift_11>=5]
 both=m11.dropna(subset=['lift_11'])
 stab={'strong_2010':int(len(strong)),'eligible':int(len(elig)),'kept':int(len(kept)),'kept_share':float(len(kept)/max(1,len(elig))),'lift_corr':float(np.corrcoef(np.log(both.lift),np.log(both.lift_11))[0,1]),'min_lift':8,'min_together':40}
 payload['affinity']={'baskets':int(allp.baskets_total.iloc[0]),'pairs':int(len(allp)),'products':int(len(set(allp.item_a)|set(allp.item_b))),'top':top_pairs,'picker':picker,'stability':stab,'period':'Dec 2009–Nov 2011'}
 print('Forecasting weekly sales and backtesting...',flush=True)
 wk=query('60_weekly.sql');wk['week']=pd.to_datetime(wk.week);series=wk.set_index('week').net;series=series.reindex(pd.date_range(series.index.min(),series.index.max(),freq='W-MON'),fill_value=0.0);WK=pd.Timedelta(weeks=1);H=13;GW=8
 def forecast(origin,h=H):
  ws=[origin+i*WK for i in range(h)];recent=series[(series.index>=origin-GW*WK)&(series.index<origin)]
  ly=np.array([series.get(w-52*WK,np.nan) for w in recent.index]);g=float(recent.sum()/np.nansum(ly))
  base=np.array([series.get(w-52*WK,np.nan) for w in ws]);return ws,base*g,base,g
 origins=[o for o in pd.date_range('2011-01-31','2011-08-22',freq='W-MON')]
 errs=[];stat=[]
 for o in origins:
  ws,f,b,g=forecast(o);a=series.reindex(ws).to_numpy();errs.append((o,np.log(a/f)));stat.append((o,np.mean(np.abs(a-f)/a),np.mean(np.abs(a-b)/a),np.mean(np.abs(a-series.iloc[-8:].mean())/a) if False else np.nan,f.sum()/a.sum()-1))
 def band(upto):
  e=np.concatenate([x for o,x in errs if o+H*WK<=upto]);return float(np.quantile(e,.10)),float(np.quantile(e,.90)),int(len(e))
 O=pd.Timestamp('2011-08-29');ws,f,b,g=forecast(O);act=series.reindex(ws).to_numpy();lo,hi,ne=band(O)
 flat=np.full(H,series[(series.index>=O-8*WK)&(series.index<O)].mean())
 acc=lambda x:{'mape':float(np.mean(np.abs(act-x)/act)),'total_error':float(x.sum()/act.sum()-1)}
 backtest={'origin':O.strftime('%d %b %Y'),'growth':g,'plotline':acc(f),'last_year':acc(b),'flat':acc(flat),'coverage':float(np.mean((act>=f*np.exp(lo))&(act<=f*np.exp(hi)))),'band_n':ne,
  'rolling':{'origins':len(origins),'mape':float(np.mean([x[1] for x in stat])),'mape_last_year':float(np.mean([x[2] for x in stat])),'abs_total_error':float(np.mean([abs(x[4]) for x in stat]))}}
 F=pd.Timestamp('2011-11-28');fws,ff,fb,fg=forecast(F);flo,fhi,fne=band(pd.Timestamp('2100-01-01'))
 fig=go.Figure()
 d=lambda ts:[t.isoformat() for t in ts]
 fig.add_trace(go.Scatter(x=d(ws)+d(ws)[::-1],y=list((f*np.exp(hi)).round(0))+list((f*np.exp(lo)).round(0))[::-1],fill='toself',fillcolor='rgba(210,161,90,.18)',line=dict(width=0),hoverinfo='skip',name='Backtest range'))
 fig.add_trace(go.Scatter(x=d(fws)+d(fws)[::-1],y=list((ff*np.exp(fhi)).round(0))+list((ff*np.exp(flo)).round(0))[::-1],fill='toself',fillcolor='rgba(117,152,178,.22)',line=dict(width=0),hoverinfo='skip',name='Forecast range'))
 fig.add_trace(go.Scatter(x=d(series.index),y=series.round(0).tolist(),mode='lines',line=dict(color=GREEN,width=2.4),name='Actual',hovertemplate='Week of %{x|%d %b %Y}<br>Actual £%{y:,.0f}<extra></extra>'))
 fig.add_trace(go.Scatter(x=d(ws),y=f.round(0).tolist(),mode='lines',line=dict(color=GOLD,width=2.2,dash='dash'),name='Backtest',hovertemplate='Week of %{x|%d %b %Y}<br>Backtest forecast £%{y:,.0f}<extra></extra>'))
 fig.add_trace(go.Scatter(x=d(fws),y=ff.round(0).tolist(),mode='lines',line=dict(color=BLUE,width=2.4,dash='dash'),name='Forecast',hovertemplate='Week of %{x|%d %b %Y}<br>Forecast £%{y:,.0f}<extra></extra>'))
 style(fig,330);fig.update_layout(hovermode='x unified',margin=dict(l=52,r=14,t=12,b=32),showlegend=False);fig.update_yaxes(tickprefix='£',tickformat='~s');fig.update_xaxes(nticks=8)
 payload['forecast']={'figure':figure(fig),'backtest':backtest,'horizon':H,'growth_window':GW,'forward':{'start':F.strftime('%d %b %Y'),'growth':fg,'total':float(ff.sum()),'low':float((ff*np.exp(flo)).sum()),'high':float((ff*np.exp(fhi)).sum()),'last_year_total':float(fb.sum()),'band_pct':[float(np.exp(flo)-1),float(np.exp(fhi)-1)]},
  'rows':[{'week':w.strftime('%Y-%m-%d'),'forecast':round(float(v),2),'low':round(float(v*np.exp(flo)),2),'high':round(float(v*np.exp(fhi)),2)} for w,v in zip(fws,ff)]}

 payload['checks']=rows(query('40_checks.sql'))
 payload['world']=world_svg()
 # Every number and chart in this bundle is generated from SQL results or trained-model outputs.
 data=json.dumps(payload,default=clean,separators=(',',':'),allow_nan=False).replace('</','<\\/')
 env=Environment(loader=FileSystemLoader(str(ROOT/'web')),autoescape=select_autoescape(['html']))
 (DIST/'index.html').write_text(env.get_template('index.html').render(bundle=data),encoding='utf-8')
 for name in ['style.css','app.js']:shutil.copy2(ROOT/'web'/name,DIST/name)
 shutil.copytree(ROOT/'web/fonts',DIST/'fonts',dirs_exist_ok=True)
 (DIST/'plotly.min.js').write_text(get_plotlyjs(),encoding='utf-8')
 (ROOT/'data/model-metrics.json').write_text(json.dumps(modelmetrics,indent=2))
 (ROOT/'data/build-audit.json').write_text(json.dumps({'source_rows':int(con.execute('SELECT count(*) FROM raw_transactions').fetchone()[0]),'ledger_rows':int(con.execute('SELECT count(*) FROM ledger').fetchone()[0]),'customers':len(customers),'train_n':len(train),'test_n':len(test),'sql_sha256':{k:hashlib.sha256(v.encode()).hexdigest() for k,v in sql.items()},'html_bytes':(DIST/'index.html').stat().st_size,'model_metrics':modelmetrics},indent=2))
 validate(payload)
 print('Dashboard built:',DIST/'index.html',flush=True)
 print(json.dumps(modelmetrics,indent=2),flush=True)

def world_svg():
 path=ROOT/'data/raw/world.geojson'
 if not path.exists():
  import urllib.request
  urllib.request.urlretrieve('https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson',path)
 data=json.loads(path.read_text());parts=[]
 for f in data['features']:
  if f['properties'].get('ADMIN')=='Antarctica':continue
  geo=f['geometry'];polygons=geo['coordinates'] if geo['type']=='MultiPolygon' else [geo['coordinates']]
  d=''
  for poly in polygons:
   ring=poly[0]
   points=[((lon+180)/360*680,(85-lat)/165*300) for lon,lat,*_ in ring]
   d+='M'+'L'.join(f'{x:.1f},{y:.1f}' for x,y in points)+'Z'
  name=f['properties'].get('ADMIN','').replace('&','&amp;').replace('"','&quot;')
  parts.append('<path data-name="'+name+'" d="'+d+'"/>')
 return '<svg viewBox="0 0 680 300" class="world-map" aria-hidden="true"><g>'+''.join(parts)+'</g><g id="mapDots"></g></svg>'

def validate(p):
 for name,v in p['overview'].items():
  s=v['summary'];assert abs(s['gross']-s['credits']-s['net'])<.01,name
  assert abs(sum(c['net'] for c in v['countries'])-s['net'])<.01,name
  assert abs(sum(c['net'] for c in v['daily'])-s['net'])<.01,name
  assert abs(v['flow_total']-s['identified_gross'])<.01,name
 for m in p['models'].values():
  assert len(m['actual'])==len(m['scores'])==p['model_meta']['test_n']
  assert 0<=m['metrics']['auc']<=1
 assert p['affinity']['top'] and p['affinity']['picker'] and 0<p['affinity']['stability']['kept_share']<=1
 assert len(p['forecast']['rows'])==p['forecast']['horizon']
 assert len(p['clusters']['points']['x'])==p['clusters']['n'] and abs(sum(x['share_spend'] for x in p['clusters']['profiles'])-1)<1e-9
 assert len(p['regression']['deciles'])==10
 assert p['source']['license']=='CC BY 4.0'
 assert next(c['value'] for c in p['checks'] if c['check_name']=='Ledger reconciliation difference')<.01
 print('Passed ledger, country, timeline, Sankey and model integrity checks.',flush=True)
if __name__=='__main__':main()
