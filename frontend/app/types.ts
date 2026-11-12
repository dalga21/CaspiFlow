export type Port={id:string;name:string;country:string;lat:number;lon:number;load:number};
export type Route={id:string;name:string;ports:string[];segments:{mode:string;km:number}[];hours:number;delay_hours:number;total_hours:number;co2_kg:number;wind:number;wave:number;load:number;interval:number[]};
export type Shipment={id:string;name:string;weight:number;owner:string;route_id:string;progress:number;container:string;updated_at:string;route:Route;alternatives:Route[];customs:{id:string;digest:string;created_at:string}|null};
export type Dashboard={shipments:Shipment[];ports:Port[];model:{name:string;mae_hours:number;train_samples:number;test_samples:number;residual_p90_hours:number};storm:number;as_of:string};
